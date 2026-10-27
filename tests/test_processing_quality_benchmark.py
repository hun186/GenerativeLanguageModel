"""Offline benchmark uses real quality JSONL, independent measurement children."""
import json
import subprocess
import sys

import pytest

from czjLLM.cli_tools import processing_quality_benchmark as bench
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
        assert entry["median_peak_traced_python_bytes"] > 0
    assert output["measurements"]["sqlite"]["median_sqlite_main_db_final_bytes"] > 0
    assert output["measurements"]["memory"]["median_sqlite_main_db_final_bytes"] is None
    assert active.read_bytes() == before
    public = json.dumps(output)
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
    assert str(tmp_path) not in json.dumps(output)


def test_digest_mismatch_including_midrun_mutation_fails_closed(monkeypatch, tmp_path):
    audit = tmp_path / "llm_call_audit_benchmark-case.csv"
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
    audit = tmp_path / "llm_call_audit_benchmark-case.csv"
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
    audit = tmp_path / "llm_call_audit_benchmark-case.csv"

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
