"""Offline quality report contract: no LLM, DB, or audit mutations."""
import json

import pytest

from czjLLM.cli_tools.processing_quality_report import (
    main, report_for_audit, report_history, summarize_quality_stream,
)
from czjLLM.utilities.processing_quality import emit_quality_event, quality_event_path


def _emit(audit, *, event, code, scope, outcome, doc=""):
    emit_quality_event(
        str(audit), run_id=audit.stem, event=event, code=code, scope=scope,
        outcome=outcome, document_id=doc,
    )


def test_observed_denominators_do_not_conflate_repair_and_schema(tmp_path):
    audit = tmp_path / "llm_call_audit_20261020-000001-1.csv"
    _emit(audit, event="slice_json_validation", code="JSON_SYNTAX_INVALID",
          scope="slice", outcome="rejected")
    _emit(audit, event="slice_json_repair", code="JSON_REPAIR_SUCCEEDED",
          scope="slice", outcome="repaired")
    _emit(audit, event="document_schema_rejected", code="SCHEMA_OTHER",
          scope="document", outcome="pending", doc="pk-1")
    _emit(audit, event="document_writeback_confirmed", code="WRITEBACK_CONFIRMED",
          scope="document", outcome="confirmed", doc="pk-1")
    content = quality_event_path(str(audit)).read_bytes()
    report = report_for_audit(audit)
    stats = report["run"]["metrics"]
    assert stats["slice_initial_invalid_pct"] == 100.0
    assert stats["repair_success_pct"] == 100.0
    assert stats["documents_schema_pending"] == 0
    assert stats["documents_writeback_confirmed"] == 1
    assert "small observed denominator" in report["run"]["sample_advisories"]["repair_success_pct"]
    assert "observed events only" in report["denominator_contract"]
    assert quality_event_path(str(audit)).read_bytes() == content
    assert "pk-1" not in json.dumps(report)


def test_missing_run_is_not_falsely_reported_as_zero(tmp_path):
    audit = tmp_path / "llm_call_audit_20261020-000001-1.csv"
    with pytest.raises(FileNotFoundError):
        report_for_audit(audit)
    with pytest.raises(ValueError, match="expected"):
        report_for_audit(tmp_path / "unrelated.csv")


def test_empty_file_is_unknown_not_zero_percent(tmp_path):
    path = tmp_path / "processing_quality_events_test.jsonl"
    path.write_bytes(b"")
    report = summarize_quality_stream(path)
    assert report["state"] == "no_valid_events"
    assert report["metrics"]["slice_initial_invalid_pct"] is None
    assert report["metrics"]["document_schema_reject_pct"] is None
    assert len(report["sample_advisories"]) == 3


def test_partial_last_line_is_not_counted(tmp_path):
    audit = tmp_path / "llm_call_audit_20261020-000001-1.csv"
    _emit(audit, event="slice_json_validation", code="JSON_VALID",
          scope="slice", outcome="valid")
    path = quality_event_path(str(audit))
    with path.open("ab") as fp:
        fp.write(b'{"schema_version":1,"event_id":"truncated')
    report = report_for_audit(audit)["run"]
    assert report["state"] == "incomplete_tail"
    assert report["metrics"]["events"] == 1
    assert report["incomplete_or_concurrent_append"] is True


def test_history_is_run_isolated_ordered_and_bounded(tmp_path):
    early = tmp_path / "llm_call_audit_20261019-111111-1.csv"
    late = tmp_path / "llm_call_audit_20261020-111111-1.csv"
    _emit(early, event="slice_json_validation", code="JSON_SYNTAX_INVALID",
          scope="slice", outcome="rejected")
    _emit(late, event="slice_json_validation", code="JSON_VALID",
          scope="slice", outcome="valid")
    report = report_history(tmp_path, limit=1)
    assert report["available_run_files"] == 2
    assert report["selected_run_files"] == 1
    assert "20261020" in report["runs"][0]["log_file"]
    assert report["runs"][0]["metrics"]["slice_initial_invalid"] == 0
    assert report_history(tmp_path, limit=20)["runs"][1]["metrics"]["slice_initial_invalid"] == 1
    with pytest.raises(ValueError, match="limit"):
        report_history(tmp_path, limit=101)


def test_cli_exports_atomically_without_rewriting_jsonl(tmp_path, capsys):
    audit = tmp_path / "llm_call_audit_20261020-111111-7.csv"
    _emit(audit, event="slice_json_validation", code="JSON_VALID",
          scope="slice", outcome="valid")
    path = quality_event_path(str(audit))
    original = path.read_bytes()
    output = tmp_path / "report.json"
    assert main(["--audit-path", str(audit), "--output", str(output)]) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["run"]["metrics"]["events"] == 1
    assert json.loads(capsys.readouterr().out)["mode"] == "single_run"
    assert path.read_bytes() == original


def test_history_empty_and_reject_log_as_report_destination(tmp_path):
    assert report_history(tmp_path)["runs"] == []
    audit = tmp_path / "llm_call_audit_20261020-111111-7.csv"
    _emit(audit, event="slice_json_validation", code="JSON_VALID",
          scope="slice", outcome="valid")
    with pytest.raises(SystemExit) as exc:
        main(["--audit-path", str(audit), "--output", str(quality_event_path(str(audit)))])
    assert exc.value.code == 2


def test_corrupt_complete_lines_are_visible_and_do_not_enter_denominator(tmp_path):
    audit = tmp_path / "llm_call_audit_20261020-222222-1.csv"
    _emit(audit, event="slice_json_validation", code="JSON_VALID",
          scope="slice", outcome="valid")
    path = quality_event_path(str(audit))
    with path.open("ab") as fp:
        fp.write(b"not a JSON event\n")
        fp.write(b"\xffinvalid utf8\n")
    report = report_for_audit(audit)["run"]
    assert report["state"] == "degraded_corrupt_lines"
    assert report["skipped_corrupt_complete_lines"] == 2
    assert report["metrics"]["events"] == 1
    assert report["metrics"]["slice_validation_attempts"] == 1
    assert report["incomplete_or_concurrent_append"] is False


def test_reader_corruption_counter_resets_on_truncation(tmp_path):
    from czjLLM.utilities.processing_quality import QualityTailReader
    path = tmp_path / "quality.jsonl"
    path.write_bytes(b"bad record\n")
    reader = QualityTailReader(str(path))
    reader.poll()
    assert reader.skipped_corrupt_lines == 1
    path.write_bytes(b"")
    reader.poll()
    assert reader.skipped_corrupt_lines == 0


def test_valid_json_invalid_event_schema_is_flagged_not_ignored(tmp_path):
    audit = tmp_path / "llm_call_audit_20261020-222222-9.csv"
    _emit(audit, event="slice_json_validation", code="JSON_VALID",
          scope="slice", outcome="valid")
    path = quality_event_path(str(audit))
    with path.open("ab") as fp:
        for record in (
            {"schema_version": 7, "event_id": "x", "event": "slice_json_repair", "code": "JSON_REPAIR_FAILED"},
            {"schema_version": 1, "event": "slice_json_repair", "code": "JSON_REPAIR_FAILED"},
            {"schema_version": 1, "event_id": "y", "event": "invented", "code": "JSON_VALID"},
            {"schema_version": 1, "event_id": "z", "event": "slice_json_repair", "code": "BAD_CODE"},
            ["valid JSON but not a quality event"],
        ):
            fp.write(json.dumps(record).encode("utf-8") + b"\n")
    report = report_for_audit(audit)["run"]
    assert report["state"] == "degraded_corrupt_lines"
    assert report["skipped_corrupt_complete_lines"] == 5
    assert report["metrics"]["events"] == 1
    assert report["metrics"]["slice_validation_attempts"] == 1


def test_duplicate_event_id_remains_deduplicated_not_corruption(tmp_path):
    audit = tmp_path / "llm_call_audit_20261020-222222-3.csv"
    _emit(audit, event="slice_json_validation", code="JSON_VALID",
          scope="slice", outcome="valid")
    path = quality_event_path(str(audit))
    line = path.read_bytes()
    with path.open("ab") as fp:
        fp.write(line)
    report = report_for_audit(audit)["run"]
    assert report["state"] == "observed"
    assert report["skipped_corrupt_complete_lines"] == 0
    assert report["metrics"]["events"] == 1


def test_fast_inplace_rewrite_longer_than_last_offset_resets_reader(tmp_path):
    from czjLLM.utilities.processing_quality import QualityTailReader
    path = tmp_path / "quality.jsonl"
    first = {
        "schema_version": 1, "event_id": "first",
        "event": "slice_json_validation", "code": "JSON_SYNTAX_INVALID",
    }
    second = {
        "schema_version": 1, "event_id": "second",
        "event": "slice_json_validation", "code": "JSON_VALID",
    }
    path.write_text(json.dumps(first) + "\n", encoding="utf-8")
    reader = QualityTailReader(str(path))
    assert reader.poll()[1]["slice_initial_invalid"] == 1
    offset = reader.offset
    # Replacement is already larger than the consumed offset at next poll.
    path.write_text(json.dumps(second) + "\n" + (" " * offset), encoding="utf-8")
    assert path.stat().st_size >= offset
    _, snapshot = reader.poll()
    assert snapshot["slice_initial_invalid"] == 0
    assert snapshot["slice_validation_attempts"] == 1


def test_atomic_replacement_equal_or_larger_resets_reader(tmp_path):
    from czjLLM.utilities.processing_quality import QualityTailReader
    path = tmp_path / "quality.jsonl"
    rec = lambda event_id, code: json.dumps({
        "schema_version": 1, "event_id": event_id,
        "event": "slice_json_validation", "code": code,
    }) + "\n"
    path.write_text(rec("a", "JSON_SYNTAX_INVALID"), encoding="utf-8")
    reader = QualityTailReader(str(path))
    reader.poll()
    size = reader.offset
    temp = tmp_path / "replacement.jsonl"
    temp.write_text(rec("b", "JSON_VALID") + " " * size, encoding="utf-8")
    temp.replace(path)
    assert path.stat().st_size >= size
    assert reader.poll()[1]["slice_initial_invalid"] == 0
    assert reader.poll()[1]["slice_validation_attempts"] == 1


def test_mismatched_codes_and_missing_document_ids_are_degraded(tmp_path):
    audit = tmp_path / "llm_call_audit_20261020-222222-4.csv"
    path = quality_event_path(str(audit))
    records = [
        {"schema_version": True, "event_id": "bool", "event": "slice_json_validation", "code": "JSON_VALID"},
        {"schema_version": 1, "event_id": "wrong-code", "event": "slice_json_validation", "code": "WRITEBACK_CONFIRMED"},
        {"schema_version": 1, "event_id": "wrong-scope", "event": "slice_json_validation", "code": "JSON_VALID", "scope": "document"},
        {"schema_version": 1, "event_id": "no-pk", "event": "document_schema_rejected", "code": "SCHEMA_OTHER"},
    ]
    path.write_text("".join(json.dumps(x) + "\n" for x in records), encoding="utf-8")
    report = report_for_audit(audit)["run"]
    assert report["state"] == "degraded_corrupt_lines"
    assert report["skipped_corrupt_complete_lines"] == len(records)
    assert report["metrics"]["events"] == 0
    assert report["metrics"]["documents_decided"] == 0


def test_conflicting_event_id_replay_degrades_but_identical_replay_does_not(tmp_path):
    audit = tmp_path / "llm_call_audit_20261020-000010-1.csv"
    _emit(audit, event="slice_json_validation", code="JSON_VALID",
          scope="slice", outcome="valid")
    path = quality_event_path(str(audit))
    original = json.loads(path.read_text(encoding="utf-8"))
    conflict = dict(original, code="JSON_SYNTAX_INVALID")
    with path.open("ab") as fp:
        # Dictionary order changes don't change the canonical record signature.
        fp.write(json.dumps(dict(reversed(list(original.items())))).encode("utf-8") + b"\n")
        fp.write(json.dumps(conflict).encode("utf-8") + b"\n")
    report = report_for_audit(audit)["run"]
    assert report["state"] == "degraded_corrupt_lines"
    assert report["skipped_corrupt_complete_lines"] == 1
    assert report["metrics"]["events"] == 1
    assert report["metrics"]["slice_initial_invalid"] == 0


def test_reader_reset_change_publishes_empty_or_corrupt_generation(tmp_path):
    from czjLLM.utilities.processing_quality import QualityTailReader
    path = tmp_path / "quality.jsonl"
    first = {
        "schema_version": 1, "event_id": "first",
        "event": "slice_json_validation", "code": "JSON_VALID",
    }
    path.write_text(json.dumps(first) + "\n", encoding="utf-8")
    reader = QualityTailReader(str(path))
    assert reader.poll()[1]["events"] == 1
    # The GUI should receive changed=True to clear its stale snapshot.
    path.write_bytes(b"")
    changed, snap = reader.poll()
    assert changed is True and snap["events"] == 0
    path.write_text("totally invalid record\n", encoding="utf-8")
    changed, snap = reader.poll()
    assert changed is False and snap["events"] == 0
    assert reader.skipped_corrupt_lines == 1
    # Restore valid then rotate atomically to corrupt, without a zero-size poll.
    path.write_text(json.dumps(first) + "\n", encoding="utf-8")
    assert reader.poll()[1]["events"] == 1
    replacement = tmp_path / "replacement.jsonl"
    replacement.write_text("wrong\n", encoding="utf-8")
    replacement.replace(path)
    changed, snap = reader.poll()
    assert changed is True and snap["events"] == 0
    assert reader.skipped_corrupt_lines == 1


def test_non_string_event_fields_are_degraded_not_type_errors(tmp_path):
    audit = tmp_path / "llm_call_audit_20261020-000011-1.csv"
    path = quality_event_path(str(audit))
    broken = {
        "schema_version": 1, "event_id": "bad", "event": [],
        "code": {"oops": True},
    }
    path.write_text(json.dumps(broken) + "\n", encoding="utf-8")
    report = report_for_audit(audit)["run"]
    assert report["state"] == "degraded_corrupt_lines"
    assert report["skipped_corrupt_complete_lines"] == 1
    assert report["metrics"]["events"] == 0


def test_nonstandard_json_constants_are_corrupt_complete_lines(tmp_path):
    audit = tmp_path / "llm_call_audit_20261021-000001-1.csv"
    _emit(audit, event="slice_json_validation", code="JSON_VALID",
          scope="slice", outcome="valid")
    path = quality_event_path(str(audit))
    valid = json.loads(path.read_text(encoding="utf-8"))
    with path.open("ab") as fp:
        for constant in ("NaN", "Infinity", "-Infinity"):
            line = json.dumps(valid).rstrip("}") + ',"extra_measurement":' + constant + "}\n"
            fp.write(line.encode("utf-8"))
    out = report_for_audit(audit)["run"]
    assert out["state"] == "degraded_corrupt_lines"
    assert out["skipped_corrupt_complete_lines"] == 3
    assert out["metrics"]["events"] == 1
    assert out["metrics"]["slice_validation_attempts"] == 1


def test_whitespace_only_event_id_and_document_id_are_not_accepted(tmp_path):
    audit = tmp_path / "llm_call_audit_20261021-000001-2.csv"
    path = quality_event_path(str(audit))
    lines = [
        {"schema_version": 1, "event_id": " \t ", "event": "slice_json_validation",
         "code": "JSON_VALID"},
        {"schema_version": 1, "event_id": "valid", "event": "document_schema_rejected",
         "code": "SCHEMA_OTHER", "document_id": "\t"},
    ]
    path.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    out = report_for_audit(audit)["run"]
    assert out["state"] == "degraded_corrupt_lines"
    assert out["skipped_corrupt_complete_lines"] == 2
    assert out["metrics"]["events"] == 0
    assert out["metrics"]["slice_validation_attempts"] == 0
    assert out["metrics"]["documents_decided"] == 0



def test_explicit_null_or_blank_scope_degrades_but_absent_scope_is_legacy_ok(tmp_path):
    audit = tmp_path / "llm_call_audit_20261021-101000-1.csv"
    path = quality_event_path(str(audit))
    rows = [
        {"schema_version": 1, "event_id": "old", "event": "slice_json_validation",
         "code": "JSON_VALID"},
        {"schema_version": 1, "event_id": "null", "event": "slice_json_validation",
         "code": "JSON_VALID", "scope": None},
        {"schema_version": 1, "event_id": "empty", "event": "slice_json_validation",
         "code": "JSON_VALID", "scope": ""},
        {"schema_version": 1, "event_id": "other", "event": "document_schema_rejected",
         "code": "SCHEMA_OTHER", "document_id": "doc", "scope": None},
        {"schema_version": 1, "event_id": "new", "event": "slice_json_validation",
         "code": "JSON_VALID", "scope": "slice"},
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    run = report_for_audit(audit)["run"]
    assert run["state"] == "degraded_corrupt_lines"
    assert run["skipped_corrupt_complete_lines"] == 3
    assert run["metrics"]["events"] == 2
    assert run["metrics"]["slice_validation_attempts"] == 2
    assert run["metrics"]["documents_decided"] == 0


def test_deeply_nested_complete_json_is_counted_corrupt_and_reader_continues(tmp_path):
    audit = tmp_path / "llm_call_audit_20261021-110000-1.csv"
    path = quality_event_path(str(audit))
    # Well-balanced JSON text, but exceeds CPython JSON decoder's safe
    # recursion depth and must not abort the entire report/GUI reader.
    excessively_nested = "[" * 2000 + "0" + "]" * 2000 + "\n"
    accepted = {
        "schema_version": 1, "event_id": "after-deep-error",
        "event": "slice_json_validation", "code": "JSON_VALID",
        "scope": "slice",
    }
    path.write_bytes(excessively_nested.encode("utf-8") +
                     (json.dumps(accepted) + "\n").encode("utf-8"))
    report = report_for_audit(audit)["run"]
    assert report["state"] == "degraded_corrupt_lines"
    assert report["skipped_corrupt_complete_lines"] == 1
    assert report["metrics"]["slice_validation_attempts"] == 1
    assert report["metrics"]["events"] == 1
    from czjLLM.utilities.processing_quality import QualityTailReader
    reader = QualityTailReader(str(path))
    changed, snapshot = reader.poll()
    assert changed is True
    assert snapshot["events"] == 1
    assert reader.skipped_corrupt_lines == 1
    assert reader.offset == path.stat().st_size
    assert reader.poll()[0] is False
