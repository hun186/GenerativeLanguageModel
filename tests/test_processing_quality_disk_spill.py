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


def test_unpaired_unicode_event_and_document_ids_match_default_reader(tmp_path):
    """A JSON escaped surrogate parses but cannot become a UTF-8 signature."""
    audit = tmp_path / "llm_call_audit_20261027-surrogate.csv"
    active = quality_event_path(str(audit))
    invalid_event = {
        "schema_version": 1, "event_id": "\\ud800",
        "event": "slice_json_validation", "code": "JSON_VALID",
    }
    invalid_document = {
        "schema_version": 1, "event_id": "bad-document",
        "event": "document_schema_rejected", "code": "SCHEMA_OTHER",
        "document_id": "\\udfff",
    }
    valid = {
        "schema_version": 1, "event_id": "accepted",
        "event": "slice_json_validation", "code": "JSON_VALID",
    }
    active.write_text(
        "".join(json.dumps(record, ensure_ascii=True) + "\\n"
                for record in (invalid_event, invalid_document, valid)),
        encoding="utf-8",
    )
    expected = summarize_quality_stream(active)
    actual = summarize_quality_stream(active, disk_backed=True)
    assert actual == expected
    assert actual["metrics"]["events"] == 1
    assert actual["skipped_corrupt_complete_lines"] == 2
    assert actual["state"] == "degraded_corrupt_lines"
    with DiskBackedQualityAccumulator() as accumulator:
        # Neither add() nor duplicate membership may fail Unicode encoding.
        assert not accumulator.add(invalid_event)
        assert not accumulator.is_identical_accepted_event(invalid_event)
        assert accumulator.add(valid)
        assert not accumulator.is_identical_accepted_event(invalid_event)


def test_private_temp_directory_create_failure_has_fixed_error(monkeypatch):
    import czjLLM.utilities.processing_quality_disk_spill as spill

    secret = "/restricted/private-user/session-cred/identity.sqlite3"

    def deny_creation(*args, **kwargs):
        raise PermissionError("private temp directory access denied: " + secret)

    monkeypatch.setattr(spill.tempfile, "TemporaryDirectory", deny_creation)
    with pytest.raises(ValueError, match="temporary quality identity index unavailable") as error:
        spill.DiskBackedQualityAccumulator()
    assert secret not in str(error.value)


def test_private_temp_cleanup_failure_has_fixed_error_and_attempts_cleanup():
    secret = "/restricted/private-user/session-cred/identity.sqlite3"
    accumulator = DiskBackedQualityAccumulator()
    directory = Path(accumulator._tmp.name)
    real_cleanup = accumulator._tmp.cleanup
    attempted = []

    def failing_cleanup():
        attempted.append(True)
        real_cleanup()
        raise PermissionError("private temporary directory cleanup failed: " + secret)

    accumulator._tmp.cleanup = failing_cleanup
    with pytest.raises(ValueError, match="temporary quality identity index unavailable") as error:
        accumulator.close()
    assert attempted == [True]
    assert secret not in str(error.value)
    assert not directory.exists()
    accumulator.close()  # idempotent even after failed cleanup notification


def test_cleanup_failure_does_not_mask_original_sanitized_sqlite_error():
    secret = "/restricted/private-user/session-cred/identity.sqlite3"
    with pytest.raises(ValueError, match="temporary quality identity index unavailable") as error:
        with DiskBackedQualityAccumulator() as accumulator:
            real_cleanup = accumulator._tmp.cleanup

            def failing_cleanup():
                real_cleanup()
                raise OSError("private cleanup path: " + secret)

            accumulator._tmp.cleanup = failing_cleanup
            raise ValueError("temporary quality identity index unavailable")
    assert secret not in str(error.value)
