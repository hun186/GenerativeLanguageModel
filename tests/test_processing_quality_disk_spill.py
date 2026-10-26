"""Physical offline JSONL and SQLite spill regressions (no live providers)."""
import json
import os
from pathlib import Path
import stat

import pytest

from czjLLM.cli_tools.processing_quality_report import (
    main, report_for_audit, report_history, summarize_quality_stream,
)
from czjLLM.utilities.processing_quality import (
    QualityAccumulator, emit_quality_event, quality_event_path,
)
from czjLLM.utilities.processing_quality_disk_spill import DiskBackedQualityAccumulator
from czjLLM.utilities.processing_quality_manifest import initialize_quality_manifest
from czjLLM.utilities.processing_quality_rotation import rotate_quality_event_stream


def _emit(audit, *, event, code, doc=""):
    emit_quality_event(
        str(audit), run_id="spill", event=event, code=code,
        scope=("document" if event.startswith("document_") else
               "run" if event.endswith("_failure") else "slice"),
        outcome="observed", document_id=doc,
    )


def test_temporary_sqlite_exact_identity_and_cleanup():
    records = [
        {"schema_version": 1, "event_id": "a", "event": "document_schema_rejected",
         "code": "SCHEMA_OTHER", "document_id": "CASE-1"},
        {"schema_version": 1, "event_id": "b", "event": "document_schema_rejected",
         "code": "SCHEMA_TIME_PRECISION", "document_id": "CASE-1"},
        {"schema_version": 1, "event_id": "c", "event": "document_writeback_confirmed",
         "code": "WRITEBACK_CONFIRMED", "document_id": "CASE-1"},
        {"schema_version": 1, "event_id": "d", "event": "document_writeback_confirmed",
         "code": "WRITEBACK_CONFIRMED", "document_id": "CASE-2"},
        {"schema_version": 1, "event_id": "e", "event": "slice_json_validation",
         "code": "JSON_SYNTAX_INVALID"},
        {"schema_version": 1, "event_id": "f", "event": "slice_json_repair",
         "code": "JSON_REPAIR_SUCCEEDED"},
        {"schema_version": 1, "event_id": "g", "event": "worker_phase_failure",
         "code": "WORKER_LLM_TIMEOUT_EXCEPTION"},
    ]
    memory = QualityAccumulator()
    with DiskBackedQualityAccumulator() as disk:
        directory = Path(disk._tmp.name)
        db = directory / "identities.sqlite3"
        assert db.is_file()
        if os.name == "posix":
            assert stat.S_IMODE(directory.stat().st_mode) == 0o700
            assert stat.S_IMODE(db.stat().st_mode) == 0o600
        for record in records:
            assert memory.add(record) and disk.add(record)
            assert not memory.add(record) and not disk.add(record)
        assert disk.is_identical_accepted_event(records[0])
        assert not disk.is_identical_accepted_event(
            {**records[0], "code": "SCHEMA_MISSING_FIELD"}
        )
        assert memory.snapshot() == disk.snapshot()
        assert disk.snapshot()["documents_decided"] == 2
        assert disk.snapshot()["documents_schema_pending"] == 0
        with pytest.raises(ValueError, match="quality source changed"):
            disk.empty_copy()
    assert not directory.exists()


def test_disk_backed_report_matches_default_across_sealed_archives_and_active(tmp_path):
    audit = tmp_path / "llm_call_audit_20261027-01.csv"
    _emit(audit, event="document_schema_rejected", code="SCHEMA_OTHER", doc="case")
    _emit(audit, event="slice_json_validation", code="JSON_SYNTAX_INVALID")
    rotate_quality_event_stream(audit)
    initialize_quality_manifest(audit)
    _emit(audit, event="document_writeback_confirmed", code="WRITEBACK_CONFIRMED", doc="case")
    _emit(audit, event="worker_phase_failure", code="WORKER_LLM_TIMEOUT_EXCEPTION")
    source = quality_event_path(str(audit))
    raw = source.read_bytes()
    # Cross-generation identical replay is not a second accepted event.
    archival = source.with_name(source.name + ".seg-00000001")
    report_memory = report_for_audit(audit)
    report_spill = report_for_audit(audit, disk_backed=True)
    assert report_spill == report_memory
    assert report_spill["run"]["archive_integrity"]["status"] == "verified"
    assert report_spill["run"]["metrics"]["documents_schema_pending"] == 0
    assert report_spill["run"]["metrics"]["worker_phase_failure_events"] == 1
    assert source.read_bytes() == raw
    assert archival.exists()


def test_disk_backed_duplicates_invalid_replay_and_partial_line_match(tmp_path):
    audit = tmp_path / "llm_call_audit_20261027-02.csv"
    _emit(audit, event="slice_json_validation", code="JSON_VALID")
    source = quality_event_path(str(audit))
    first = json.loads(source.read_text(encoding="utf-8"))
    with source.open("ab") as fp:
        fp.write((json.dumps(first) + "\n").encode("utf-8"))
        fp.write((json.dumps({**first, "code": "JSON_SYNTAX_INVALID"}) + "\n").encode("utf-8"))
        fp.write(b"invalid-json\n")
        fp.write(b'{"schema_version": 1, "event_id": "incomplete')
    expected = summarize_quality_stream(source)
    actual = summarize_quality_stream(source, disk_backed=True)
    assert actual == expected
    assert actual["metrics"]["events"] == 1
    assert actual["skipped_corrupt_complete_lines"] == 2
    assert actual["state"] == "degraded_corrupt_lines"


def test_disk_backed_cli_and_history_keep_report_contract(tmp_path, capsys):
    audit = tmp_path / "llm_call_audit_20261027-03.csv"
    _emit(audit, event="document_schema_rejected", code="SCHEMA_OTHER", doc="never-export-this")
    output = tmp_path / "quality-summary.json"
    assert main(["--audit-path", str(audit), "--disk-backed", "--output", str(output)]) == 0
    single = json.loads(output.read_text(encoding="utf-8"))
    assert single == report_for_audit(audit)
    assert "never-export-this" not in json.dumps(single)
    capsys.readouterr()
    assert report_history(tmp_path, disk_backed=True) == report_history(tmp_path)
    assert main(["--audit-dir", str(tmp_path), "--disk-backed", "--limit", "1"]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "run_history"


def test_disk_backed_fail_closed_on_invalid_archive_and_no_sqlite_residue(tmp_path):
    audit = tmp_path / "llm_call_audit_20261027-04.csv"
    _emit(audit, event="slice_json_validation", code="JSON_VALID")
    rotate_quality_event_stream(audit)
    initialize_quality_manifest(audit)
    segment = quality_event_path(str(audit)).with_name(
        quality_event_path(str(audit)).name + ".seg-00000001"
    )
    segment.write_bytes(segment.read_bytes().replace(b"JSON_VALID", b"JSON_SAVED"))
    with pytest.raises(ValueError):
        report_for_audit(audit, disk_backed=True)
    assert list(tmp_path.glob("czjllm-quality-*")) == []
