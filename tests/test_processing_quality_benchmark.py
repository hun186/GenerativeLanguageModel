"""Offline benchmark uses real quality JSONL, independent measurement children."""
import ast
import ctypes
from types import SimpleNamespace
import json
from pathlib import Path
import subprocess
import sys

import pytest

from czjLLM.cli_tools import processing_quality_benchmark as bench
from czjLLM.cli_tools import processing_quality_process_memory as winmem
from czjLLM.utilities.processing_quality import emit_quality_event, quality_event_path
from czjLLM.utilities.processing_quality_manifest import initialize_quality_manifest
from czjLLM.utilities.processing_quality_rotation import rotate_quality_event_stream


def _audit_with_archives(tmp_path):
    audit = tmp_path / "llm_call_audit_benchmark-case.csv"
    emit_quality_event(
        str(audit), run_id="benchmark-case",
        event="document_schema_rejected", code="SCHEMA_OTHER",
        scope="document", outcome="pending", document_id="sensitive-private-key",
    )
    rotate_quality_event_stream(audit)
    initialize_quality_manifest(audit)
    emit_quality_event(
        str(audit), run_id="benchmark-case",
        event="document_writeback_confirmed", code="WRITEBACK_CONFIRMED",
        scope="document", outcome="confirmed", document_id="sensitive-private-key",
    )
    return audit


def test_actual_isolated_process_report_parity_and_sanitized_output(tmp_path):
    audit = _audit_with_archives(tmp_path)
    active = quality_event_path(str(audit))
    before = active.read_bytes()
    output = bench.benchmark_quality_run(audit, repetitions=2)
    assert output["benchmark_version"] == 1
    assert output["parity"] == "matching_complete_report_sha256"
    assert output["repetitions"] == 2
    assert len(output["report_sha256"]) == 64
    for mode in ("memory", "sqlite"):
        entry = output["measurements"][mode]
        assert entry["samples"] == 2
        assert entry["median_seconds"] >= 0
        assert entry["median_subprocess_wall_seconds"] >= entry["median_seconds"]
        assert entry["median_peak_traced_python_bytes"] > 0
    assert output["measurements"]["sqlite"]["median_sqlite_main_db_final_bytes"] > 0
    assert output["measurements"]["memory"]["median_sqlite_main_db_final_bytes"] is None
    assert active.read_bytes() == before
    public = json.dumps(output, allow_nan=False)
    assert str(tmp_path) not in public
    assert "sensitive-private-key" not in public
    assert "processing_quality_events_" not in public


def test_cli_single_repetition_json_output_and_privacy(tmp_path, capsys):
    audit = _audit_with_archives(tmp_path)
    assert bench.main([
        "--audit-path", str(audit), "--repetitions", "1", "--timeout", "300",
    ]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["repetitions"] == 1
    assert output["measurements"]["sqlite"]["samples"] == 1
    assert output["measurements"]["sqlite"]["median_subprocess_wall_seconds"] > 0
    assert str(tmp_path) not in json.dumps(output)


def test_digest_mismatch_including_midrun_mutation_fails_closed(monkeypatch, tmp_path):
    audit = _audit_with_archives(tmp_path)
    counter = [0]

    def different_reports(_path, mode, _timeout):
        counter[0] += 1
        return {
            "report_sha256": "a" * 64 if counter[0] == 1 else "b" * 64,
            "mode": mode,
            "elapsed_seconds": 1.0,
            "peak_traced_python_bytes": 2000,
            "peak_process_rss_bytes": None,
            "sqlite_main_db_final_bytes": None,
        }

    monkeypatch.setattr(bench, "_sample", different_reports)
    with pytest.raises(ValueError, match="parity changed"):
        bench.benchmark_quality_run(audit, repetitions=1)
    assert counter[0] == 2


def test_subprocess_failure_masks_stderr_private_file_path(monkeypatch, tmp_path):
    audit = _audit_with_archives(tmp_path)
    secret = "/private/internal/run-id/credentials"

    def failed_process(*args, **kwargs):
        assert kwargs["input"].find("audit_path") != -1
        assert "--worker" in args[0]
        assert secret not in args[0]
        return subprocess.CompletedProcess(args[0], 1, "", secret)

    monkeypatch.setattr(bench.subprocess, "run", failed_process)
    with pytest.raises(ValueError, match="quality benchmark worker failed") as error:
        bench.benchmark_quality_run(audit, repetitions=1)
    assert secret not in str(error.value)


def test_timeout_and_worker_response_fail_closed(monkeypatch, tmp_path):
    audit = _audit_with_archives(tmp_path)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(bench.subprocess, "run", timeout)
    with pytest.raises(ValueError, match="worker unavailable"):
        bench.benchmark_quality_run(audit, repetitions=1)


@pytest.mark.parametrize("repetitions,timeout", [
    (0, 300), (6, 300), (True, 300),
    (1, 0), (1, 3601), (1, False),
])
def test_invalid_benchmark_limits_rejected(tmp_path, repetitions, timeout):
    audit = tmp_path / "llm_call_audit_benchmark-case.csv"
    with pytest.raises(ValueError):
        bench.benchmark_quality_run(
            audit, repetitions=repetitions, timeout=timeout
        )


def test_worker_rejects_malformed_request_without_echoing_raw_data(monkeypatch, capsys):
    from io import StringIO

    class FakeInput:
        def read(self, _limit):
            return '{"audit_path":"/private/top-secret","mode":"wrong"}'

    monkeypatch.setattr(sys, "stdin", FakeInput())
    assert bench._worker() == 1
    read = capsys.readouterr()
    assert "/private/top-secret" not in read.out + read.err


@pytest.mark.parametrize("args", [
    ["--audit-path", "/private/secret_audit.csv",
     "--repetitions", "/private/secret-repetitions.csv"],
    ["--audit-path", "/private/secret_audit.csv",
     "--timeout", "/private/secret-timeout.csv"],
    ["--audit-path", "/private/secret_audit.csv", "/private/secret-extra.jsonl"],
    ["--audit-path", "/private/secret_audit.csv", "--repetitions", "0"],
    ["--repetitions", "2"],
])
def test_real_cli_parser_error_never_echoes_private_paths(args):
    """Validate native argparse failures, not only worker errors."""
    result = subprocess.run(
        [sys.executable, "-m", "czjLLM.cli_tools.processing_quality_benchmark",
         *args],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == "quality benchmark: invalid arguments\n"
    assert "/private/" not in result.stderr


def test_benchmark_imports_are_not_inside_try_blocks():
    """Enforce AGENTS.md: dependency imports must be outside try/except."""
    path = Path(bench.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for block in ast.walk(tree):
        if isinstance(block, ast.Try):
            for statement in block.body:
                assert not isinstance(statement, (ast.Import, ast.ImportFrom))


def _fixed_sample(_path, mode, _timeout):
    """Only measurements are substituted; source inputs are real physical files."""
    return {
        "report_sha256": "a" * 64,
        "mode": mode,
        "elapsed_seconds": 1.0,
        "peak_traced_python_bytes": 2000,
        "peak_process_rss_bytes": None,
        "sqlite_main_db_final_bytes": None,
    }


def test_source_generation_changes_on_append_even_if_report_digest_same(
    monkeypatch, tmp_path
):
    audit = _audit_with_archives(tmp_path)
    active = quality_event_path(str(audit))
    called = []

    def append_during_sample(path, mode, timeout):
        called.append(mode)
        with active.open("ab") as writer:
            writer.write(b"not-a-quality-record\n")
        return _fixed_sample(path, mode, timeout)

    monkeypatch.setattr(bench, "_sample", append_during_sample)
    with pytest.raises(ValueError, match="source changed during measurement") as error:
        bench.benchmark_quality_run(audit, repetitions=1)
    assert called == ["memory"]
    assert str(tmp_path) not in str(error.value)


def test_source_generation_changes_on_manifest_rewrite_without_metric_change(
    monkeypatch, tmp_path
):
    from czjLLM.utilities.processing_quality_manifest import manifest_path

    audit = _audit_with_archives(tmp_path)
    ledger = manifest_path(quality_event_path(str(audit)))
    called = []

    def rewrite_manifest(path, mode, timeout):
        called.append(mode)
        with ledger.open("ab") as writer:
            writer.write(b" ")
        return _fixed_sample(path, mode, timeout)

    monkeypatch.setattr(bench, "_sample", rewrite_manifest)
    with pytest.raises(ValueError, match="source changed during measurement"):
        bench.benchmark_quality_run(audit, repetitions=1)
    assert called == ["memory"]


def test_source_generation_changes_on_new_archived_shard(
    monkeypatch, tmp_path
):
    audit = _audit_with_archives(tmp_path)
    active = quality_event_path(str(audit))
    shard = active.with_name(active.name + ".seg-00000002")
    first = active.with_name(active.name + ".seg-00000001")

    def add_shard(path, mode, timeout):
        shard.write_bytes(first.read_bytes())
        return _fixed_sample(path, mode, timeout)

    monkeypatch.setattr(bench, "_sample", add_shard)
    with pytest.raises(ValueError, match="source changed during measurement"):
        bench.benchmark_quality_run(audit, repetitions=1)


def test_missing_quality_stream_rejected_without_fake_performance(tmp_path):
    audit = tmp_path / "llm_call_audit_no-events.csv"
    with pytest.raises(ValueError, match="source snapshot unavailable"):
        bench.benchmark_quality_run(audit, repetitions=1)


def test_source_generation_rejects_symlinked_active_and_manifest(tmp_path):
    from czjLLM.utilities.processing_quality_manifest import manifest_path

    audit = _audit_with_archives(tmp_path)
    active = quality_event_path(str(audit))
    ledger = manifest_path(active)
    original = active.with_name("fixture-original.jsonl")
    active.rename(original)
    try:
        active.symlink_to(original)
    except (NotImplementedError, OSError):
        pytest.skip("symlink creation unavailable on this runner")
    with pytest.raises(ValueError, match="source snapshot unavailable"):
        bench.benchmark_quality_run(audit, repetitions=1)
    active.unlink()
    original.rename(active)

    original_ledger = ledger.with_name("fixture-original-manifest.json")
    ledger.rename(original_ledger)
    ledger.symlink_to(original_ledger)
    with pytest.raises(ValueError, match="source snapshot unavailable"):
        bench.benchmark_quality_run(audit, repetitions=1)


def test_windows_memory_probe_unavailable_outside_windows():
    if sys.platform != "win32":
        assert winmem.windows_peak_working_set_bytes() is None


def test_windows_memory_probe_uses_correct_psapi_process_fields(monkeypatch):
    """Linux CI simulates Windows API calling contract; no Windows claim."""
    observed = []

    def get_current_process():
        return 12345

    def get_memory_info(process, ptr, size):
        assert process == 12345
        assert size == ctypes.sizeof(winmem._ProcessMemoryCounters)
        output = ctypes.cast(
            ptr, ctypes.POINTER(winmem._ProcessMemoryCounters)
        ).contents
        assert output.cb == ctypes.sizeof(winmem._ProcessMemoryCounters)
        output.PeakWorkingSetSize = 987654
        observed.append("called")
        return 1

    def fake_dll(name, *, use_last_error=False):
        assert use_last_error is True
        if name == "kernel32":
            return SimpleNamespace(GetCurrentProcess=get_current_process)
        assert name == "psapi"
        return SimpleNamespace(GetProcessMemoryInfo=get_memory_info)

    with monkeypatch.context() as patch:
        patch.setattr(winmem.sys, "platform", "win32")
        patch.setattr(winmem.ctypes, "WinDLL", fake_dll, raising=False)
        assert winmem.windows_peak_working_set_bytes() == 987654
    assert observed == ["called"]


def test_windows_memory_probe_api_errors_are_null_and_path_free(monkeypatch):
    secret = "/private/sensitive/quality-ids"

    def broken_dll(*args, **kwargs):
        raise OSError(secret)

    with monkeypatch.context() as patch:
        patch.setattr(winmem.sys, "platform", "win32")
        patch.setattr(winmem.ctypes, "WinDLL", broken_dll, raising=False)
        assert winmem.windows_peak_working_set_bytes() is None


def test_windows_memory_probe_failed_api_status_is_null(monkeypatch):
    def handle():
        return 42

    def failed_info(_handle, _ptr, _size):
        return 0

    def fake_dll(name, *, use_last_error=False):
        if name == "kernel32":
            return SimpleNamespace(GetCurrentProcess=handle)
        return SimpleNamespace(GetProcessMemoryInfo=failed_info)

    with monkeypatch.context() as patch:
        patch.setattr(winmem.sys, "platform", "win32")
        patch.setattr(winmem.ctypes, "WinDLL", fake_dll, raising=False)
        assert winmem.windows_peak_working_set_bytes() is None


@pytest.mark.skipif(sys.platform != "win32", reason="requires real Windows OS")
def test_native_windows_memory_probe_real_current_process():
    """Operator/self-hosted Windows gate: actual PSAPI current-process call."""
    value = winmem.windows_peak_working_set_bytes()
    assert type(value) is int
    assert value > 0


def test_parent_measures_subprocess_wall_without_trusting_worker_value(
    monkeypatch, tmp_path
):
    """Wall clock belongs to parent; worker cannot forge it through stdout."""
    audit = tmp_path / "llm_call_audit_private.csv"
    result = {
        "mode": "memory",
        "report_sha256": "a" * 64,
        "elapsed_seconds": 0.25,
        "peak_traced_python_bytes": 1024,
        "peak_process_rss_bytes": None,
        "sqlite_main_db_final_bytes": None,
        "subprocess_wall_seconds": 9999,
    }
    calls = []

    def completed_process(command, **kwargs):
        calls.append(command)
        assert kwargs["timeout"] == 42
        assert kwargs["input"] == json.dumps({
            "audit_path": str(audit), "mode": "memory",
        })
        assert str(audit) not in " ".join(command)
        return subprocess.CompletedProcess(command, 0, json.dumps(result), "")

    clocks = iter([10.0, 10.875001])
    with monkeypatch.context() as patch:
        patch.setattr(bench.subprocess, "run", completed_process)
        patch.setattr(bench.time, "perf_counter", lambda: next(clocks))
        measured = bench._sample(audit, "memory", 42)

    assert len(calls) == 1
    assert measured["elapsed_seconds"] == 0.25
    assert measured["subprocess_wall_seconds"] == pytest.approx(0.875001)
    assert str(audit) not in json.dumps(measured)


def test_benchmark_preserves_report_median_and_adds_subprocess_median(
    monkeypatch, tmp_path
):
    audit = _audit_with_archives(tmp_path)
    calls = []

    def measured_sample(_path, mode, _timeout):
        calls.append(mode)
        result = _fixed_sample(_path, mode, _timeout)
        result["elapsed_seconds"] = 0.4 if mode == "memory" else 0.8
        result["subprocess_wall_seconds"] = 2.2 if mode == "memory" else 3.2
        return result

    monkeypatch.setattr(bench, "_sample", measured_sample)
    result = bench.benchmark_quality_run(audit, repetitions=2)
    assert calls == ["memory", "sqlite", "sqlite", "memory"]
    assert result["measurements"]["memory"]["median_seconds"] == 0.4
    assert result["measurements"]["sqlite"]["median_seconds"] == 0.8
    assert result["measurements"]["memory"]["median_subprocess_wall_seconds"] == 2.2
    assert result["measurements"]["sqlite"]["median_subprocess_wall_seconds"] == 3.2
    assert str(tmp_path) not in json.dumps(result)


@pytest.mark.parametrize("field,value", [
    ("elapsed_seconds", float("nan")),
    ("elapsed_seconds", float("inf")),
    ("elapsed_seconds", float("-inf")),
    ("elapsed_seconds", -0.1),
    ("elapsed_seconds", True),
    ("elapsed_seconds", 10 ** 400),
    ("peak_traced_python_bytes", float("nan")),
    ("peak_traced_python_bytes", float("inf")),
    ("peak_traced_python_bytes", 3.5),
    ("peak_traced_python_bytes", True),
])
def test_worker_nonfinite_or_noninteger_measurements_fail_closed(
    monkeypatch, tmp_path, field, value
):
    """Do not let non-JSON or bogus physical metrics reach published medians."""
    audit = tmp_path / "llm_call_audit_sensitive.csv"
    reply = {
        "mode": "memory",
        "report_sha256": "a" * 64,
        "elapsed_seconds": 0.25,
        "peak_traced_python_bytes": 1000,
        "peak_process_rss_bytes": None,
        "sqlite_main_db_final_bytes": None,
    }
    reply[field] = value
    secret = "/secret/private/audit-path"

    def worker(command, **kwargs):
        assert secret not in " ".join(command)
        return subprocess.CompletedProcess(
            command, 0, json.dumps(reply), secret
        )

    monkeypatch.setattr(bench.subprocess, "run", worker)
    with pytest.raises(
        ValueError, match="invalid quality benchmark worker response"
    ) as failure:
        bench._sample(audit, "memory", 10)
    assert str(audit) not in str(failure.value)
    assert secret not in str(failure.value)


def test_nonstandard_json_number_in_unused_worker_field_is_rejected(
    monkeypatch, tmp_path
):
    audit = tmp_path / "llm_call_audit_private.csv"
    reply = (
        '{"mode":"memory","report_sha256":"' + "a" * 64
        + '","elapsed_seconds":0.5,"peak_traced_python_bytes":100,'
        + '"peak_process_rss_bytes":null,"sqlite_main_db_final_bytes":null,'
        + '"ignored":NaN}'
    )
    monkeypatch.setattr(
        bench.subprocess, "run",
        lambda args, **kw: subprocess.CompletedProcess(args, 0, reply, ""),
    )
    with pytest.raises(ValueError, match="invalid quality benchmark worker response"):
        bench._sample(audit, "memory", 10)


@pytest.mark.parametrize("end_time", [float("nan"), float("inf"), -5.0])
def test_invalid_parent_subprocess_wall_clock_is_unavailable(
    monkeypatch, tmp_path, end_time
):
    audit = tmp_path / "llm_call_audit_hidden.csv"
    seen = iter((4.0, end_time))
    monkeypatch.setattr(bench.time, "perf_counter", lambda: next(seen))
    monkeypatch.setattr(
        bench.subprocess, "run",
        lambda args, **kw: subprocess.CompletedProcess(args, 0, "{}", ""),
    )
    with pytest.raises(ValueError, match="quality benchmark worker unavailable") as failure:
        bench._sample(audit, "memory", 10)
    assert str(audit) not in str(failure.value)


def test_cli_rejects_invalid_summary_json_without_partial_output(
    monkeypatch, tmp_path, capsys
):
    """Defense in depth if an upstream contract regresses after validation."""
    fake = {"measurements": {"memory": {"median_seconds": float("nan")}}}
    monkeypatch.setattr(bench, "benchmark_quality_run", lambda *a, **kw: fake)
    with pytest.raises(SystemExit) as result:
        bench.main(["--audit-path", str(tmp_path / "llm_call_audit_private.csv")])
    captured = capsys.readouterr()
    assert result.value.code == 2
    assert captured.out == ""
    assert captured.err == "quality benchmark: invalid arguments\n"
    assert str(tmp_path) not in captured.err
