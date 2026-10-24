"""Offline actual-file quality rotation/replay regression without LLM/network/DB."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from czjLLM.cli_tools.processing_quality_report import report_for_audit, report_history
from czjLLM.cli_tools.processing_quality_rotate import main
from czjLLM.utilities.processing_quality import emit_quality_event, quality_event_path
from czjLLM.utilities.processing_quality_rotation import (
    quality_stream_segments, rotate_quality_event_stream,
)


def _emit(audit, event, code, *, scope="run", doc=""):
    return emit_quality_event(
        str(audit), run_id="public-run", event=event, code=code,
        scope=scope, outcome="observed", document_id=doc,
    )


def test_real_rotation_multiple_segments_replay_distinct_document_recovery(tmp_path):
    audit = tmp_path / "llm_call_audit_20261024-one.csv"
    _emit(audit, "document_schema_rejected", "SCHEMA_OTHER",
          scope="document", doc="private-identity")
    _emit(audit, "worker_phase_failure", "WORKER_LLM_TIMEOUT_EXCEPTION")
    stream = quality_event_path(str(audit))
    generation1 = stream.read_bytes()
    assert rotate_quality_event_stream(audit) == {
        "rotated": True, "archived_segments": 1,
    }
    assert not stream.exists()
    archived = quality_stream_segments(stream)
    assert len(archived) == 1 and archived[0].read_bytes() == generation1
    # Archive-only run remains visible, not treated as an empty or missing log.
    first = report_for_audit(audit)["run"]
    assert first["state"] == "observed"
    assert first["archived_segments"] == 1
    assert first["metrics"]["documents_schema_pending"] == 1
    assert first["metrics"]["worker_phase_failure_events"] == 1
    assert report_history(tmp_path)["available_run_files"] == 1

    _emit(audit, "document_writeback_confirmed", "WRITEBACK_CONFIRMED",
          scope="document", doc="private-identity")
    second = report_for_audit(audit)["run"]
    assert second["archived_segments"] == 1
    assert second["metrics"]["events"] == 3
    assert second["metrics"]["documents_schema_pending"] == 0
    assert second["metrics"]["documents_writeback_confirmed"] == 1
    # Existing run accumulator deduplicates repeat IDs across physical shards.
    assert rotate_quality_event_stream(audit)["archived_segments"] == 2
    _emit(audit, "worker_phase_failure", "WORKER_LLM_RATE_LIMIT_EXCEPTION")
    original_new = stream.read_bytes()
    stream.write_bytes(generation1.splitlines(keepends=True)[0] + original_new)
    third = report_for_audit(audit)["run"]
    assert third["archived_segments"] == 2
    assert third["metrics"]["events"] == 4
    assert third["metrics"]["documents_schema_pending"] == 0
    assert third["metrics"]["worker_phase_failure_events"] == 2
    assert third["skipped_corrupt_complete_lines"] == 0
    assert third["incident_diagnostics"]["observed_run_incident_events"] == 2
    assert "private-identity" not in json.dumps(third["incident_diagnostics"])
    assert archived[0].read_bytes() == generation1


def test_rotation_refuses_incomplete_record_without_mutating_existing_bytes(tmp_path):
    audit = tmp_path / "llm_call_audit_20261024-partial.csv"
    _emit(audit, "worker_phase_failure", "WORKER_LLM_CONNECTION_EXCEPTION")
    stream = quality_event_path(str(audit))
    with stream.open("ab") as fp:
        fp.write(b'{"schema_version":1,"incomplete')
    before = stream.read_bytes()
    with pytest.raises(ValueError, match="incomplete final record"):
        rotate_quality_event_stream(audit)
    assert stream.read_bytes() == before
    assert quality_stream_segments(stream) == []


def test_empty_stream_noop_and_bounded_archive_budget_never_prunes(tmp_path):
    audit = tmp_path / "llm_call_audit_20261024-limit.csv"
    stream = quality_event_path(str(audit))
    stream.write_bytes(b"")
    assert rotate_quality_event_stream(audit)["rotated"] is False
    _emit(audit, "worker_phase_failure", "WORKER_LLM_TIMEOUT_EXCEPTION")
    assert rotate_quality_event_stream(audit, max_segments=1)["archived_segments"] == 1
    archive = quality_stream_segments(stream)[0]
    old = archive.read_bytes()
    _emit(audit, "worker_phase_failure", "WORKER_LLM_HTTP_SERVER_EXCEPTION")
    new = stream.read_bytes()
    with pytest.raises(ValueError, match="budget"):
        rotate_quality_event_stream(audit, max_segments=1)
    assert stream.read_bytes() == new
    assert archive.read_bytes() == old


def test_missing_or_noncanonical_archive_segment_fails_closed(tmp_path):
    audit = tmp_path / "llm_call_audit_20261024-gap.csv"
    _emit(audit, "worker_phase_failure", "WORKER_LLM_TIMEOUT_EXCEPTION")
    stream = quality_event_path(str(audit))
    rotate_quality_event_stream(audit)
    _emit(audit, "stage_orchestration_failure", "STAGE_PREPARE_EXCEPTION")
    rotate_quality_event_stream(audit)
    segments = quality_stream_segments(stream)
    segments[0].rename(stream.with_name(stream.name + ".seg-00000003"))
    with pytest.raises(ValueError, match="missing or invalid segment"):
        report_for_audit(audit)
    with pytest.raises(ValueError, match="missing or invalid segment"):
        rotate_quality_event_stream(audit)
    # Invalid suffix must never silently vanish from history.
    (stream.parent / (stream.name + ".seg-TRUNCATED")).write_bytes(b"irrelevant\n")
    with pytest.raises(ValueError, match="noncanonical"):
        quality_stream_segments(stream)


def test_corrupt_or_partial_archived_segment_is_not_declared_complete(tmp_path):
    audit = tmp_path / "llm_call_audit_20261024-damaged.csv"
    _emit(audit, "worker_phase_failure", "WORKER_LLM_TIMEOUT_EXCEPTION")
    stream = quality_event_path(str(audit))
    rotate_quality_event_stream(audit)
    segment = quality_stream_segments(stream)[0]
    segment.write_bytes(segment.read_bytes() + b"bad-closed-record\n")
    result = report_for_audit(audit)["run"]
    assert result["state"] == "degraded_corrupt_lines"
    assert result["metrics"]["worker_phase_failure_events"] == 1
    assert result["skipped_corrupt_complete_lines"] == 1
    segment.write_bytes(segment.read_bytes() + b"partial")
    result = report_for_audit(audit)["run"]
    assert result["state"] == "degraded_incomplete_archive"
    assert result["incomplete_or_concurrent_append"] is True


def test_manual_cli_requires_operator_stop_acknowledgement_and_no_private_data(tmp_path, capsys):
    audit = tmp_path / "llm_call_audit_20261024-cli.csv"
    _emit(audit, "worker_phase_failure", "WORKER_LLM_TIMEOUT_EXCEPTION")
    with pytest.raises(SystemExit) as x:
        main(["--audit-path", str(audit)])
    assert x.value.code == 2
    with pytest.raises(SystemExit) as x:
        main(["--audit-path", str(tmp_path / "not-a-run.csv"), "--confirm-stopped"])
    assert x.value.code == 2
    capsys.readouterr()
    assert main(["--audit-path", str(audit), "--confirm-stopped"]) == 0
    text = capsys.readouterr().out
    assert json.loads(text) == {
        "mode": "manual_quality_rotation",
        "rotated": True,
        "archived_segments": 1,
    }
    assert "20261024" not in text and str(tmp_path) not in text


def test_symlink_active_rejected_and_archive_never_removed(tmp_path):
    audit = tmp_path / "llm_call_audit_20261024-link.csv"
    stream = quality_event_path(str(audit))
    target = tmp_path / "raw.jsonl"
    target.write_bytes(b'{"sample":1}\n')
    try:
        stream.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink not supported")
    with pytest.raises(ValueError, match="symlink"):
        rotate_quality_event_stream(audit)
    assert target.read_bytes() == b'{"sample":1}\n'
