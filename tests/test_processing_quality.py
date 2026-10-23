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



def test_unacknowledged_sinks_do_not_report_durable_success():
    from pathlib import Path
    code = Path("czjLLM/sql_mode/runtime/row_merger_generic.py").read_text(
        encoding="utf-8"
    )
    confirmation = code.index('if callable(confirm_writeback):')
    event = code.index('event="document_writeback_confirmed"')
    assert confirmation < event
    # The event must sit under the conditional guard rather than an
    # unconditional success path shared by Excel/CSV.
    fragment = code[confirmation:event]
    assert fragment.count("if callable(confirm_writeback):") == 2
    assert 'if callable(confirm_writeback):\n                        try:' in fragment


def test_quality_tail_reader_does_not_count_valid_duplicate_as_corruption(tmp_path):
    path = tmp_path / "quality.jsonl"
    rec = {"schema_version": 1, "event_id": "same",
           "event": "slice_json_validation", "code": "JSON_VALID"}
    path.write_text(json.dumps(rec) + "\n" + json.dumps(rec) + "\n", encoding="utf-8")
    reader = QualityTailReader(str(path))
    assert reader.poll()[1]["events"] == 1
    assert reader.skipped_corrupt_lines == 0


def test_quality_producer_rejects_event_code_scope_mismatch(tmp_path):
    audit = str(tmp_path / "llm_call_audit_invalid.csv")
    import pytest
    with pytest.raises(ValueError, match="mismatched quality event/code"):
        emit_quality_event(
            audit, event="slice_json_validation", code="SCHEMA_OTHER",
            scope="slice", outcome="invalid"
        )
    with pytest.raises(ValueError, match="mismatched quality event scope"):
        emit_quality_event(
            audit, event="slice_json_validation", code="JSON_VALID",
            scope="document", outcome="valid"
        )
    assert not quality_event_path(audit).exists()


def test_reader_reset_alone_reports_changed_for_gui_consumer(tmp_path):
    path = tmp_path / "quality.jsonl"
    record = {"schema_version": 1, "event_id": "one",
              "event": "slice_json_validation", "code": "JSON_VALID"}
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    reader = QualityTailReader(str(path))
    reader.poll()
    path.write_bytes(b"")
    changed, stats = reader.poll()
    assert changed and stats["events"] == 0


def test_quality_accumulator_rejects_nonstandard_python_nan_and_blank_ids():
    a = QualityAccumulator()
    record = {"schema_version": 1, "event_id": "x",
              "event": "slice_json_validation", "code": "JSON_VALID",
              "extra": float("nan")}
    assert a.add(record) is False
    record.pop("extra")
    record["event_id"] = " \t "
    assert a.add(record) is False
    assert a.snapshot()["events"] == 0



def test_explicit_null_scope_rejected_but_absent_legacy_scope_accepted():
    a = QualityAccumulator()
    legacy = {"schema_version": 1, "event_id": "old", "event": "slice_json_validation",
              "code": "JSON_VALID"}
    assert a.add(legacy)
    assert not a.add({**legacy, "event_id": "bad", "scope": None})
    assert not a.add({**legacy, "event_id": "bad2", "scope": ""})
    assert a.add({**legacy, "event_id": "ok", "scope": "slice"})
    assert a.snapshot()["events"] == 2


def test_gui_quality_schema_failure_labels_are_unambiguous():
    from pathlib import Path
    from czjLLM.job_manager.win_gui import format_quality_summary
    stats = QualityAccumulator().snapshot()
    summary = format_quality_summary(stats)
    assert "LLM 文件結構異常（待處理）" in summary
    ui = Path("czjLLM/job_manager/win_gui.py").read_text(encoding="utf-8")
    assert "文件結構驗證未通過 / 已判定文件" in ui


def test_consumer_orchestration_incidents_are_not_document_or_slice_failures(tmp_path):
    audit = str(tmp_path / "llm_call_audit_consumer.csv")
    for code in ("CONSUMER_ROUND_TIMEOUT", "CONSUMER_ROUND_EXCEPTION",
                 "CONSUMER_TERMINATED"):
        emit_quality_event(
            audit, run_id="r-consumer", event="consumer_orchestration_failure",
            code=code, scope="run", outcome="observed",
        )
    path = quality_event_path(audit)
    rows = [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 3
    assert all(row["scope"] == "run" and not row["document_id"]
               and not row["slice_id"] for row in rows)
    assert all("exception" not in row and "error" not in row and "prompt" not in row
               for row in rows)
    changed, stats = QualityTailReader(str(path)).poll()
    assert changed and stats["consumer_orchestration_failure_events"] == 3
    assert stats["events"] == 3
    assert stats["slice_validation_attempts"] == stats["repair_attempts"] == 0
    assert stats["documents_decided"] == 0
    assert stats["slice_initial_invalid_pct"] is None
    assert stats["document_schema_reject_pct"] is None
    assert stats["error_codes"]["CONSUMER_ROUND_TIMEOUT"] == 1
    assert stats["error_codes"]["CONSUMER_ROUND_EXCEPTION"] == 1
    assert stats["error_codes"]["CONSUMER_TERMINATED"] == 1


def test_consumer_incident_bad_scope_and_code_fail_closed(tmp_path):
    import pytest
    audit = str(tmp_path / "llm_call_audit_invalid.csv")
    with pytest.raises(ValueError, match="mismatched quality event scope"):
        emit_quality_event(audit, event="consumer_orchestration_failure",
                           code="CONSUMER_ROUND_TIMEOUT", scope="slice",
                           outcome="observed")
    with pytest.raises(ValueError, match="unknown or mismatched quality event/code"):
        emit_quality_event(audit, event="consumer_orchestration_failure",
                           code="JSON_VALID", scope="run", outcome="observed")
    assert not quality_event_path(audit).exists()
    assert not QualityAccumulator().add({
        "schema_version": 1, "event_id": "bad", "event": "consumer_orchestration_failure",
        "code": "CONSUMER_ROUND_EXCEPTION", "scope": "document",
    })


def test_consumer_incident_production_wiring_and_gui_label():
    from pathlib import Path
    from czjLLM.job_manager.win_gui import format_quality_summary
    code = Path("czjLLM/prompt_pipeline/pipeline_controller.py").read_text(encoding="utf-8")
    for value in ("CONSUMER_ROUND_TIMEOUT", "CONSUMER_ROUND_EXCEPTION",
                  "CONSUMER_TERMINATED"):
        assert f'_audit_consumer_orchestration_failure(ctx, "{value}")' in code
    assert "Consumer 調度異常 0 次（事件數）" in format_quality_summary(
        QualityAccumulator().snapshot())


def test_consumer_run_events_refuse_document_and_slice_id_at_write_boundary(tmp_path):
    import pytest
    audit = str(tmp_path / "llm_call_audit_no_identity.csv")
    for identities in (
        {"document_id": "sensitive-id"},
        {"slice_id": "TODO/sensitive-slice.txt"},
        {"document_id": " ", "slice_id": " "},
        {"document_id": None},
        {"slice_id": None},
    ):
        with pytest.raises(ValueError, match="cannot carry document or slice identities"):
            emit_quality_event(
                audit, event="consumer_orchestration_failure",
                code="CONSUMER_ROUND_TIMEOUT", scope="run", outcome="observed",
                **identities,
            )
    assert not quality_event_path(audit).exists()


def test_consumer_run_reader_rejects_identity_bearing_complete_jsonl(tmp_path):
    path = tmp_path / "processing_quality_events_bad-identities.jsonl"
    base = {
        "schema_version": 1,
        "event": "consumer_orchestration_failure",
        "code": "CONSUMER_ROUND_TIMEOUT",
        "scope": "run",
    }
    bad = [
        {**base, "event_id": "doc", "document_id": "sensitive-document"},
        {**base, "event_id": "slice", "slice_id": "sensitive-slice"},
        {**base, "event_id": "null", "document_id": None},
    ]
    good = {**base, "event_id": "valid", "document_id": "", "slice_id": ""}
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in bad + [good]),
        encoding="utf-8",
    )
    reader = QualityTailReader(str(path))
    changed, stats = reader.poll()
    assert changed
    assert reader.skipped_corrupt_lines == len(bad)
    assert stats["events"] == 1
    assert stats["consumer_orchestration_failure_events"] == 1
    assert stats["documents_decided"] == 0
    assert stats["slice_validation_attempts"] == 0
    assert not QualityAccumulator().add(bad[0])
    assert not QualityAccumulator().add(bad[1])
