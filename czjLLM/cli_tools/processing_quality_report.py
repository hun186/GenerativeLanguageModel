# -*- coding: utf-8 -*-
"""Read-only, offline reports from the existing per-run quality JSONL streams.

This module never invokes an LLM, opens a database, or modifies an audit log.
Results are observational, not an ES read-after-refresh or cross-sink success gate.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import json
from pathlib import Path
from typing import Any

from czjLLM.utilities.atomic_io import atomic_write_json
from czjLLM.utilities.processing_quality import (
    QualityAccumulator, QualityTailReader, RUN_INCIDENT_CODES, quality_event_path,
)
from czjLLM.utilities.processing_quality_rotation import quality_stream_segments
from czjLLM.utilities.processing_quality_disk_spill import DiskBackedQualityAccumulator
from czjLLM.utilities.processing_quality_manifest import verify_quality_manifest

LOW_SAMPLE_ADVISORY_THRESHOLD = 30
_METRIC_DENOMINATORS = {
    "slice_initial_invalid_pct": "slice_validation_attempts",
    "repair_success_pct": "repair_attempts",
    "document_schema_reject_pct": "documents_decided",
}
_FILE_PREFIX = "processing_quality_events_"
_FILE_SUFFIX = ".jsonl"


def run_incident_diagnostics(
    metrics: dict[str, Any], *, family: str | None = None,
) -> dict[str, Any]:
    """Project only the prevalidated run-scoped code counters, without raw IDs.

    Share percentages refer to the *observed incident event* denominator only.
    They are not request failure rates, failed-document rates or deduped causes.
    """
    if family is not None and family not in RUN_INCIDENT_CODES:
        raise ValueError("unknown run-scoped incident family")
    codes = metrics["error_codes"]
    families = {}
    for name, allowed in RUN_INCIDENT_CODES.items():
        observed_codes = {
            code: codes[code] for code in sorted(allowed) if codes.get(code, 0)
        }
        families[name] = {
            "observed_events": sum(observed_codes.values()),
            "codes": observed_codes,
        }

    observed_total = sum(item["observed_events"] for item in families.values())
    names = [family] if family is not None else sorted(families)
    selected = {}
    for name in names:
        count = families[name]["observed_events"]
        selected[name] = {
            **families[name],
            "share_of_observed_incidents_pct": (
                round(100 * count / observed_total, 2) if observed_total else None
            ),
        }
    return {
        "scope": "run",
        "denominator_contract": (
            "observed run-scoped incident events only; overlapping catch sites "
            "may count the same logical failure; not HTTP attempts, requests "
            "or distinct failed documents"
        ),
        "focus_family": family,
        "observed_run_incident_events": observed_total,
        "families": selected,
        "sample_advisory": (
            "no observed run-scoped incident events; share is unknown"
            if not observed_total else
            f"small observed incident denominator (n={observed_total}); "
            "interpret shares cautiously"
            if observed_total < LOW_SAMPLE_ADVISORY_THRESHOLD else ""
        ),
    }


def summarize_quality_stream(
    path: str | Path, *, incident_family: str | None = None,
    disk_backed: bool = False,
) -> dict[str, Any]:
    """Summarize one explicit log, without including document IDs or event payloads."""
    if incident_family is not None and incident_family not in RUN_INCIDENT_CODES:
        raise ValueError("unknown run-scoped incident family")
    source = Path(path)
    archives = quality_stream_segments(source)
    archive_integrity = verify_quality_manifest(source, archives)
    if source.is_symlink():
        raise ValueError("refusing a symlink quality event stream")
    if source.exists() and not source.is_file():
        raise ValueError("quality event stream must be a regular file")
    if not source.is_file() and not archives:
        raise FileNotFoundError(f"quality event stream does not exist: {source.name}")

    def identity(file):
        if not file.exists():
            return None
        st = file.stat()
        return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns

    before_active = identity(source)
    before_archives = [identity(segment) for segment in archives]
    # Ephemeral SQLite is opt-in. The default remains entirely read-only and
    # in-memory; the temporary index is removed even on validation failures.
    with (DiskBackedQualityAccumulator() if disk_backed else
          nullcontext(QualityAccumulator())) as accumulator:
        corrupt_lines = 0
        incomplete = False
        incomplete_archive = False
        # The same validated accumulator preserves cross-shard event-id dedup and
        # document writeback recovery semantics. Only this one run is aggregated.
        for segment in archives + ([source] if source.is_file() else []):
            reader = QualityTailReader(str(segment), accumulator=accumulator)
            reader.poll()
            corrupt_lines += reader.skipped_corrupt_lines
            missing_tail = segment.stat().st_size > reader.offset
            incomplete = incomplete or missing_tail
            if segment != source and missing_tail:
                incomplete_archive = True
        # Fail closed on maintenance rotation while a report is being assembled.
        # Concurrent ordinary appends retain their historical incomplete state.
        if quality_stream_segments(source) != archives:
            raise ValueError("quality segment generation changed during reporting")
        if [identity(segment) for segment in archives] != before_archives:
            raise ValueError("quality archived segment changed during reporting")
        # Check again to catch a changed ledger/archive while replaying. A
        # mismatch is a hard error, never an apparently complete summary.
        if verify_quality_manifest(source, archives) != archive_integrity:
            raise ValueError("quality archive ledger changed during reporting")
        changed_during_read = identity(source) != before_active
        incomplete = incomplete or changed_during_read
        stats = accumulator.snapshot()
        sample_notes = {}
        for pct, denom in _METRIC_DENOMINATORS.items():
            n = int(stats[denom])
            if n == 0:
                sample_notes[pct] = "no observed denominator; rate is unknown"
            elif n < LOW_SAMPLE_ADVISORY_THRESHOLD:
                sample_notes[pct] = (
                    f"small observed denominator (n={n}); interpret rate cautiously"
                )
        return {
            "log_file": source.name,
            "state": ("degraded_incomplete_archive" if incomplete_archive else
                      "degraded_corrupt_lines" if corrupt_lines else
                      "incomplete_tail" if incomplete else
                      "no_valid_events" if not stats["events"] else "observed"),
            "skipped_corrupt_complete_lines": corrupt_lines,
            "archived_segments": len(archives),
            "archive_integrity": archive_integrity,
            "metrics": stats,
            "incident_diagnostics": run_incident_diagnostics(stats, family=incident_family),
            "sample_advisories": sample_notes,
            "incomplete_or_concurrent_append": incomplete,
        }


def report_for_audit(
    audit_path: str | Path, *, incident_family: str | None = None,
    disk_backed: bool = False,
) -> dict[str, Any]:
    """Derive the companion JSONL from the canonical LLM audit CSV filename."""
    audit = Path(audit_path)
    if audit.suffix.lower() != ".csv" or not audit.name.startswith("llm_call_audit_"):
        raise ValueError("expected llm_call_audit_<run_id>.csv")
    companion = quality_event_path(str(audit))
    if companion is None:
        raise ValueError("missing audit path")
    return {
        "report_version": 1,
        "mode": "single_run",
        "denominator_contract": "observed events only; not all processed documents",
        "confirmed_writeback_contract": "explicit sink acknowledgement only (currently ES); not ES readback",
        "run": summarize_quality_stream(companion, incident_family=incident_family, disk_backed=disk_backed),
    }


def report_history(
    audit_dir: str | Path, *, limit: int = 20,
    incident_family: str | None = None, disk_backed: bool = False,
) -> dict[str, Any]:
    """Show the latest named run streams, ordered by sortable timestamped run ID."""
    directory = Path(audit_dir)
    if not directory.is_dir():
        raise FileNotFoundError(f"audit directory does not exist: {directory}")
    if directory.is_symlink():
        raise ValueError("refusing a symlink audit directory")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100")
    if incident_family is not None and incident_family not in RUN_INCIDENT_CODES:
        raise ValueError("unknown run-scoped incident family")
    # Include runs with only completed numbered archives after explicit
    # maintenance rotation; the stable active basename may not yet exist.
    discovered = set()
    for item in directory.glob(_FILE_PREFIX + "*"):
        if item.is_symlink() or not item.is_file():
            continue
        name = item.name
        if name.endswith(_FILE_SUFFIX):
            discovered.add(item)
        elif _FILE_SUFFIX + ".seg-" in name:
            stable, _suffix = name.split(_FILE_SUFFIX + ".seg-", 1)
            discovered.add(directory / (stable + _FILE_SUFFIX))
        elif name.endswith(_FILE_SUFFIX + ".manifest.json"):
            # A ledger with all shards missing must still be discovered so
            # verification fails closed instead of silently omitting the run.
            discovered.add(directory / name[:-len(".manifest.json")])
    candidates = sorted(discovered, key=lambda p: p.name, reverse=True)
    runs = [
        summarize_quality_stream(p, incident_family=incident_family, disk_backed=disk_backed)
        for p in candidates[:limit]
    ]
    return {
        "report_version": 1,
        "mode": "run_history",
        "denominator_contract": "each run is isolated; no cross-run denominator aggregation",
        "confirmed_writeback_contract": "explicit sink acknowledgement only (currently ES); not ES readback",
        "available_run_files": len(candidates),
        "selected_run_files": len(runs),
        "runs": runs,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline read-only quality summary from logs/llm_call_audit"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--audit-path", type=Path, help="llm_call_audit_<run_id>.csv")
    source.add_argument("--audit-dir", type=Path, help="directory of per-run JSONL logs")
    parser.add_argument("--limit", type=int, default=20, help="history rows (1..100)")
    parser.add_argument(
        "--incident-family", choices=sorted(RUN_INCIDENT_CODES), default=None,
        help="focus the run-only incident breakdown without filtering raw metrics",
    )
    parser.add_argument("--disk-backed", action="store_true",
                        help="use an ephemeral local SQLite identity index to reduce retained RAM; "
                             "requires private temporary disk space")
    parser.add_argument("--output", type=Path, help="optional atomic JSON report output")
    args = parser.parse_args(argv)
    try:
        result = (
            report_for_audit(args.audit_path, incident_family=args.incident_family,
                             disk_backed=args.disk_backed)
            if args.audit_path is not None else report_history(
                args.audit_dir, limit=args.limit, incident_family=args.incident_family,
                disk_backed=args.disk_backed
            )
        )
        if args.output is not None:
            if args.output.suffix.lower() != ".json":
                raise ValueError("output path must end in .json, not a source log")
            # Never overwrite an input CSV/JSONL. This is a report-only writer.
            atomic_write_json(str(args.output), result, ensure_ascii=False)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
