"""No-payload per-work-item lineage for common numbered TODO/1.txt slices."""
from __future__ import annotations

import json
from pathlib import Path

from czjLLM.utilities.quality_slice_lineage import quality_slice_location_hints
from czjLLM.utilities.processing_quality import (
    QualityAccumulator, emit_quality_event, quality_event_path,
)
from czjLLM.utilities.processing_quality_run_reader import QualityRunTailReader
from czjLLM.utilities.json_repair_analysis import analyze_json_repair


def _valid_detail():
    try:
        json.loads('{"a":1,}')
    except json.JSONDecodeError as exc:
        code, metrics = analyze_json_repair('{"a":1,}', '{"a":1}', exc)
    return dict(metrics, repair_class=code)


def test_same_numbered_slice_in_different_work_items_never_uses_basename_only(tmp_path):
    first = tmp_path / "private-source-1" / "TODO" / "1.txt"
    second = tmp_path / "private-source-2" / "TODO" / "1.txt"
    a_item, a_slice = quality_slice_location_hints(str(first))
    b_item, b_slice = quality_slice_location_hints(str(second))
    assert len(a_item) == len(a_slice) == 24
    assert a_item != b_item and a_slice != b_slice
    assert first.name == second.name == "1.txt"


def test_todo_to_running_same_trace_and_different_number_same_work_item(tmp_path):
    root = tmp_path / "document-A"
    item_todo, slice_todo = quality_slice_location_hints(str(root / "TODO" / "1.txt"))
    item_running, slice_running = quality_slice_location_hints(str(root / "RUNNING" / "1.txt"))
    item_success, slice_success = quality_slice_location_hints(str(root / "Success" / "1.txt"))
    other_item, other_slice = quality_slice_location_hints(str(root / "TODO" / "2.txt"))
    assert item_todo == item_running == item_success == other_item
    assert slice_todo == slice_running == slice_success
    assert other_slice != slice_todo


def test_unsupported_no_context_returns_empty_pair(tmp_path):
    for value in ("", "/tmp/prompt.txt", "1.txt", str(tmp_path / "DONE" / "1.txt"),
                  str(tmp_path / "TODO" / "1.json"), "a\x00.txt", "x" * 4097):
        assert quality_slice_location_hints(value) == ("", "")
    assert quality_slice_location_hints(None) == ("", "")


def test_event_stream_and_gui_distinguish_independent_todo_1_txt(tmp_path):
    audit = tmp_path / "llm_call_audit_r.csv"
    detail = _valid_detail()
    roots = ["tenantA/private_item1", "tenantB/private_item2"]
    for root in roots:
        for queue in ("TODO", "RUNNING"):
            emit_quality_event(
                str(audit), run_id="run-1", event="slice_json_repair",
                code="JSON_REPAIR_SUCCEEDED", scope="slice", outcome="recovered",
                slice_id=str(tmp_path / root / queue / "1.txt"), detail=detail,
            )
    stream = quality_event_path(str(audit))
    wire = stream.read_text(encoding="utf-8")
    assert "tenantA" not in wire and "tenantB" not in wire
    assert "private_item" not in wire
    assert "/TODO/" not in wire and "/RUNNING/" not in wire
    records = [json.loads(line) for line in wire.splitlines()]
    assert len(records) == 4
    assert all(r["slice_id"] == "1.txt" for r in records)
    assert records[0]["work_item_hint"] == records[1]["work_item_hint"]
    assert records[0]["slice_trace_hint"] == records[1]["slice_trace_hint"]
    assert records[0]["work_item_hint"] != records[2]["work_item_hint"]
    assert records[0]["slice_trace_hint"] != records[2]["slice_trace_hint"]
    reader = QualityRunTailReader(str(stream))
    changed, stats = reader.poll()
    assert changed and stats["repair_succeeded"] == 4
    recent = stats["repair_analysis_recent"]
    assert recent[0]["slice_hint"] == recent[1]["slice_hint"]
    assert recent[0]["slice_hint"] != recent[2]["slice_hint"]
    assert recent[0]["work_item_hint"] == recent[1]["work_item_hint"]
    assert recent[0]["work_item_hint"] != recent[2]["work_item_hint"]
    assert all(c["lineage_status"] == "ITEM_PATH_DERIVED" for c in recent)
    assert "tenantA" not in json.dumps(stats)
    assert "tenantB" not in json.dumps(stats)


def test_legacy_archive_keeps_basename_warning_and_unknown_source_linkage():
    detail = _valid_detail()
    a = QualityAccumulator()
    for i in range(2):
        assert a.add({
            "schema_version": 1,
            "event_id": "old" + str(i),
            "event": "slice_json_repair",
            "code": "JSON_REPAIR_SUCCEEDED", "scope": "slice",
            "run_id": "legacy", "slice_id": "1.txt",
            "detail": detail,
        })
    cases = a.snapshot()["repair_analysis_recent"]
    assert len(cases) == 2
    assert cases[0]["slice_hint"] == cases[1]["slice_hint"]
    assert all(c["work_item_hint"] == "" for c in cases)
    assert all(c["lineage_status"] == "BASENAME_ONLY" for c in cases)


def test_forged_lineage_tokens_are_rejected_at_reader_boundary():
    good = {
        "schema_version": 1, "event_id": "test", "event": "slice_json_repair",
        "code": "JSON_REPAIR_SUCCEEDED", "scope": "slice",
        "work_item_hint": "0" * 24, "slice_trace_hint": "f" * 24,
    }
    assert QualityAccumulator().add(good)
    for change in (
        {"work_item_hint": "../private"},
        {"slice_trace_hint": "NOT_HEX"},
        {"work_item_hint": "F" * 24},
        {"slice_trace_hint": None},
    ):
        forged = dict(good, event_id="bad", **change)
        assert not QualityAccumulator().add(forged)
    for absent in ("work_item_hint", "slice_trace_hint"):
        forged = {k:v for k,v in good.items() if k != absent}
        assert not QualityAccumulator().add(forged)
    forged = dict(good, event_id="wrong-scope", event="worker_phase_failure",
                  code="WORKER_PRECALL_EXCEPTION", scope="run",
                  slice_id="")
    assert not QualityAccumulator().add(forged)
