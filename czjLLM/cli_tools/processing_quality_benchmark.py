"""Opt-in, read-only performance/parity probe for an existing quality run.

Each sample starts a clean Python subprocess to compare the original in-memory
offline report with the temporary-SQLite backend. No source rows or identities
are serialized into benchmark results. This is measurement, not a guaranteed
memory ceiling, checkpoint or permission to rotate an active producer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import stat
import statistics
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path

from czjLLM.cli_tools import processing_quality_report as reports
from czjLLM.cli_tools.processing_quality_process_memory import windows_peak_working_set_bytes
from czjLLM.utilities.processing_quality import quality_event_path
from czjLLM.utilities.processing_quality_manifest import manifest_path
from czjLLM.utilities.processing_quality_rotation import quality_stream_segments

# resource is absent from Windows. Choose supported platforms BEFORE import,
# instead of importing inside a try/except (AGENTS.md repository requirement).
if sys.platform.startswith("linux") or sys.platform == "darwin":
    import resource


_MODES = ("memory", "sqlite")
_MAX_REQUEST = 16 * 1024


def _worker() -> int:
    """Only called as a private fresh-process measurement child."""
    try:
        raw = sys.stdin.read(_MAX_REQUEST + 1)
        if len(raw) > _MAX_REQUEST:
            raise ValueError("oversized benchmark worker request")
        req = json.loads(raw)
        if not isinstance(req, dict) or set(req) != {"audit_path", "mode"}:
            raise ValueError("invalid benchmark worker request")
        if not isinstance(req["audit_path"], str) or not req["audit_path"]:
            raise ValueError("invalid audit path")
        mode = req["mode"]
        if mode not in _MODES:
            raise ValueError("invalid benchmark mode")

        temp_size = []
        if mode == "sqlite":
            # Private instrumentation in this *child process only*. Collect
            # the final main SQLite file size just before report cleanup.
            # This is NOT cumulative bytes written or total journal/OS I/O.
            base = reports.DiskBackedQualityAccumulator

            class MeasuredAccumulator(base):
                def close(self):
                    root = getattr(self, "_tmp", None)
                    if root is not None:
                        try:
                            size = (Path(root.name) / "identities.sqlite3").stat().st_size
                            temp_size.append(size)
                        except OSError:
                            pass
                    return super().close()

            reports.DiskBackedQualityAccumulator = MeasuredAccumulator

        tracemalloc.start()
        start = time.perf_counter()
        report = reports.report_for_audit(
            req["audit_path"], disk_backed=(mode == "sqlite")
        )
        seconds = time.perf_counter() - start
        _current, traced_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        # Linux ru_maxrss is KiB, macOS is bytes; Windows PSAPI reports
        # PeakWorkingSetSize (resident working-set high-water), not commit.
        rss = None
        if sys.platform.startswith("linux") or sys.platform == "darwin":
            try:
                units = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                if sys.platform.startswith("linux"):
                    rss = int(units * 1024)
                else:
                    rss = int(units)
            except (OSError, ValueError):
                pass
        elif sys.platform == "win32":
            rss = windows_peak_working_set_bytes()

        canonical = json.dumps(
            report, sort_keys=True, ensure_ascii=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        result = {
            "mode": mode,
            "elapsed_seconds": round(seconds, 6),
            "peak_traced_python_bytes": traced_peak,
            "peak_process_rss_bytes": rss,
            "sqlite_main_db_final_bytes": (
                max(temp_size) if temp_size else None
            ),
            "report_sha256": hashlib.sha256(canonical).hexdigest(),
        }
        sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
        return 0
    except Exception:
        # Do not disclose source filenames, temp paths, raw IDs or payloads
        # to stderr, even if the worker is accidentally run directly.
        sys.stderr.write("quality benchmark worker failed\n")
        return 1


def _sample(audit_path: Path, mode: str, timeout: int) -> dict:
    request = json.dumps({"audit_path": str(audit_path), "mode": mode})
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "czjLLM.cli_tools.processing_quality_benchmark",
             "--worker"],
            input=request, capture_output=True, text=True, timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("quality benchmark worker unavailable") from None
    if proc.returncode != 0:
        raise ValueError("quality benchmark worker failed") from None
    try:
        result = json.loads(proc.stdout)
        if not isinstance(result, dict) or result.get("mode") != mode:
            raise ValueError("invalid worker result")
        signature = result["report_sha256"]
        if not (isinstance(signature, str) and len(signature) == 64
                and all(c in "0123456789abcdef" for c in signature)):
            raise ValueError("invalid worker digest")
        for name in ("elapsed_seconds", "peak_traced_python_bytes"):
            if (isinstance(result.get(name), bool)
                    or not isinstance(result.get(name), (int, float))
                    or result[name] < 0):
                raise ValueError("invalid worker measurement")
        for name in ("peak_process_rss_bytes", "sqlite_main_db_final_bytes"):
            value = result.get(name)
            if value is not None and (
                    type(value) is not int or value < 0):
                raise ValueError("invalid optional measurement")
        return result
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("invalid quality benchmark worker response") from None


def _source_generation(audit_path: Path) -> tuple:
    """Bounded path/metadata generation guard for a *stopped* quality run.

    This is a cheap, read-only race detector, NOT an atomic snapshot, source
    lock, hash of active bytes, or protection against hostile metadata replay.
    Do not expose filenames/identities from the internal tuple in CLI output.
    """
    active = quality_event_path(str(audit_path))
    if active is None:
        raise ValueError("quality benchmark source snapshot unavailable")
    try:
        segments = quality_stream_segments(active)
        ledger = manifest_path(active)
        observed = []
        present = False
        for path in [*segments, active, ledger]:
            try:
                info = path.lstat()
            except FileNotFoundError:
                if path in segments:
                    raise ValueError("quality benchmark source snapshot unavailable") from None
                observed.append((path.name, None))
                continue
            if not stat.S_ISREG(info.st_mode) or (
                getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            ):
                raise ValueError("quality benchmark source snapshot unavailable")
            if path == active or path in segments:
                present = True
            observed.append((
                path.name, info.st_dev, info.st_ino, info.st_size,
                info.st_mtime_ns, info.st_ctime_ns,
            ))
        if not present:
            raise ValueError("quality benchmark requires an existing quality stream")
        return tuple(observed)
    except (OSError, ValueError):
        raise ValueError("quality benchmark source snapshot unavailable") from None


def benchmark_quality_run(
    audit_path: str | Path, *, repetitions: int = 2, timeout: int = 300,
) -> dict:
    """Measure both modes on the *same stable run*; abort on parity drift.

    Each sample is a fresh subprocess; timed region excludes imports and
    process startup. Input must be an existing stopped-producer quality run.
    Lightweight before/after metadata checks catch many source-generation
    races even if output metrics happen to match. They are not a lock or
    authenticated hash of active content.
    This function and its outputs never modify JSONL, archive or manifest.
    """
    if type(repetitions) is not int or not 1 <= repetitions <= 5:
        raise ValueError("repetitions must be an integer between 1 and 5")
    if type(timeout) is not int or not 1 <= timeout <= 3600:
        raise ValueError("timeout must be an integer between 1 and 3600")
    source = Path(audit_path)
    if (source.suffix.lower() != ".csv"
            or not source.name.startswith("llm_call_audit_")):
        raise ValueError("expected canonical LLM audit CSV run name")
    # A matching report digest is not enough: a run may be appended, replaced,
    # or have its manifest updated without changing the aggregate metrics.
    baseline = _source_generation(source)
    samples = {mode: [] for mode in _MODES}
    digests = set()
    for index in range(repetitions):
        # Alternate run order to reduce warmed filesystem cache bias.
        for mode in (_MODES if index % 2 == 0 else reversed(_MODES)):
            if _source_generation(source) != baseline:
                raise ValueError("quality benchmark source changed during measurement")
            measured = _sample(source, mode, timeout)
            if _source_generation(source) != baseline:
                raise ValueError("quality benchmark source changed during measurement")
            digests.add(measured["report_sha256"])
            if len(digests) != 1:
                raise ValueError(
                    "quality benchmark parity changed: source or report differs"
                )
            samples[mode].append(measured)

    summary = {}
    for mode, entries in samples.items():
        summary[mode] = {
            "samples": len(entries),
            "median_seconds": statistics.median(
                e["elapsed_seconds"] for e in entries
            ),
            "median_peak_traced_python_bytes": statistics.median(
                e["peak_traced_python_bytes"] for e in entries
            ),
            "median_peak_process_rss_bytes": (
                statistics.median(
                    e["peak_process_rss_bytes"] for e in entries
                ) if all(e["peak_process_rss_bytes"] is not None
                         for e in entries) else None
            ),
            "median_sqlite_main_db_final_bytes": (
                statistics.median(
                    e["sqlite_main_db_final_bytes"] for e in entries
                ) if all(e["sqlite_main_db_final_bytes"] is not None
                         for e in entries) else None
            ),
        }

    return {
        "benchmark_version": 1,
        "mode": "offline_quality_single_run",
        "parity": "matching_complete_report_sha256",
        "report_sha256": next(iter(digests)),
        "repetitions": repetitions,
        "measurements": summary,
        "measurement_notes": (
            "Fresh child process per sample; tracemalloc changes timing; "
            "RSS is OS high-water including interpreter and libraries; "
            "Windows is peak resident working set (not private commit), "
            "null if unavailable; SQLite DB size excludes other "
            "temporary files and total bytes written; no guaranteed memory "
            "or latency savings and no live producer/ES acceptance."
        ),
    }


class _PrivateArgumentParser(argparse.ArgumentParser):
    """Do not reflect malformed path-valued CLI arguments to stderr."""

    def error(self, _message: str) -> None:
        self.exit(2, "quality benchmark: invalid arguments\n")


def main(argv: list[str] | None = None) -> int:
    parser = _PrivateArgumentParser(
        description="Compare exact offline quality report cost without raw data output"
    )
    parser.add_argument("--audit-path", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args(argv)
    try:
        result = benchmark_quality_run(
            args.audit_path, repetitions=args.repetitions, timeout=args.timeout
        )
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--worker"]:
        raise SystemExit(_worker())
    raise SystemExit(main())
