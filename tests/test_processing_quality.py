"""Regression: quality counters must never confuse slice and document failure."""
import json
from czjLLM.utilities.processing_quality import (
    QualityAccumulator, QualityTailReader, classify_schema_error,
    emit_quality_event, quality_event_path,
)


def test_run_scoped_event_stream_and_no_raw_payload(tmp_path):
    audit = str(tmp_path / "llm_call_audit_20261020-1.csv")
    path = quality_event_path(audit)
    assert path.name == "processing_quality_events_20261020-1.jsonl"
    emit_quality_event(audit, run_id="r1", event="slice_json_validation",
                       code="JSON_SYNTAX_INVALID", scope="slice", outcome="rejected",
                       slice_id=str(tmp_path / "TODO" / "3.txt"))
    rec = json.loads(path.read_text(encoding="utf-8"))
    assert rec["slice_id"] == "3.txt"
    assert "raw_output" not in rec and "prompt" not in rec
    assert rec["run_id"] == "r1"


def test_unknown_denominators_and_repair_does_not_mean_document_failure():
    a = QualityAccumulator()
    empty = a.snapshot()
    assert empty["slice_initial_invalid_pct"] is None
    assert empty["document_schema_reject_pct"] is None
    records = [
        ("a", "slice_json_validation", "JSON_SYNTAX_INVALID", ""),
        ("b", "slice_json_repair", "JSON_REPAIR_SUCCEEDED", ""),
        ("c", "slice_json_validation", "JSON_VALID", ""),
        ("d", "document_schema_rejected", "SCHEMA_MISSING_FIELD", "pkA"),
        ("e", "document_schema_rejected", "SCHEMA_TIME_PRECISION", "pkA"),
        ("f", "document_writeback_confirmed", "WRITEBACK_CONFIRMED", "pkB"),
    ]
    for event_id, event, code, pk in records:
        rec = {"schema_version": 1, "event_id": event_id, "event": event,
               "code": code, "document_id": pk}
        assert a.add(rec)
        assert not a.add(rec)
    stats = a.snapshot()
    assert stats["slice_validation_attempts"] == 2
    assert stats["slice_initial_invalid_pct"] == 50.0
    assert stats["repair_success_pct"] == 100.0
    assert stats["documents_decided"] == 2
    assert stats["documents_schema_pending"] == 1
    assert stats["documents_writeback_confirmed"] == 1
    assert stats["document_schema_reject_pct"] == 50.0
    a.add({"schema_version": 1, "event_id": "g", "event": "document_writeback_confirmed",
           "code": "WRITEBACK_CONFIRMED", "document_id": "pkA"})
    assert a.snapshot()["documents_schema_pending"] == 0
    assert a.snapshot()["documents_decided"] == 2


def test_tail_reader_skips_partial_line_and_handles_truncation(tmp_path):
    path = tmp_path / "quality.jsonl"
    reader = QualityTailReader(str(path))
    record = {"schema_version": 1, "event_id": "1", "event": "slice_json_validation",
              "code": "JSON_SYNTAX_INVALID"}
    wire = (json.dumps(record) + "\n").encode("utf-8")
    path.write_bytes(wire[:9])
    changed, stats = reader.poll()
    assert not changed and stats["events"] == 0 and reader.offset == 0
    path.write_bytes(wire)
    changed, stats = reader.poll()
    assert changed and stats["slice_initial_invalid"] == 1
    assert reader.poll()[0] is False
    path.write_bytes(b"")
    assert reader.poll()[1]["events"] == 0


def test_known_schema_categories():
    assert classify_schema_error("Event_Timeline[5].event_ids is required by the current schema") == "SCHEMA_MISSING_FIELD"
    assert classify_schema_error("precision='day' requires a date-only time_iso") == "SCHEMA_TIME_PRECISION"
    assert classify_schema_error("missing event_ids reference") == "SCHEMA_EVENT_REFERENCE"
    assert classify_schema_error("other bad payload") == "SCHEMA_OTHER"


def test_quality_gui_wiring_and_percent_unit_labels():
    from pathlib import Path
    from czjLLM.job_manager.win_gui import format_quality_summary
    stats = QualityAccumulator().snapshot()
    text = format_quality_summary(stats)
    assert "樣本不足" in text and "0 筆" in text
    gui = Path("czjLLM/job_manager/win_gui.py").read_text(encoding="utf-8")
    runtime = Path("czjLLM/sql_mode/runtime/runtime_ui.py").read_text(encoding="utf-8")
    assert "_quality_reader_worker" in gui
    assert "set_quality_event_path" in gui and "QUALITY_PATH" in gui
    assert "quality_frame.pack_forget()" in gui
    assert "quality_event_path(audit_path)" in runtime


def test_production_emitters_are_connected_without_console_regex():
    from pathlib import Path
    pipeline = Path("czjLLM/prompt_pipeline/pipeline_controller.py").read_text(encoding="utf-8")
    row = Path("czjLLM/sql_mode/runtime/row_merger_generic.py").read_text(encoding="utf-8")
    assert '"slice_json_validation", "JSON_SYNTAX_INVALID"' in pipeline
    assert '"slice_json_repair", "JSON_REPAIR_SUCCEEDED"' in pipeline
    assert 'event="document_schema_rejected"' in row
    assert 'event="document_writeback_confirmed"' in row
    assert row.index('confirm_writeback()') < row.index('event="document_writeback_confirmed"')


def test_long_document_keys_remain_distinct(tmp_path):
    audit = str(tmp_path / "llm_call_audit_long.csv")
    prefix = "D" * 200
    first, second = prefix + "A", prefix + "B"
    path = quality_event_path(audit)
    for event, code, document_id in [
        ("document_schema_rejected", "SCHEMA_MISSING_FIELD", first),
        ("document_writeback_confirmed", "WRITEBACK_CONFIRMED", second),
    ]:
        emit_quality_event(
            audit, run_id="same-run", event=event, code=code, scope="document",
            outcome="pending" if event == "document_schema_rejected" else "confirmed",
            document_id=document_id,
        )
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert all(row["document_id"].startswith("sha256:") for row in lines)
    assert lines[0]["document_id"] != lines[1]["document_id"]
    reader = QualityTailReader(str(path))
    assert reader.poll()[1]["documents_schema_pending"] == 1
    assert reader.poll()[1]["documents_decided"] == 2
