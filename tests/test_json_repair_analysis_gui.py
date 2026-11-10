"""JSON repair comparisons from real Worker strings to privacy-safe GUI events."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from czjLLM.job_manager.win_gui import (
    format_json_repair_analysis_case,
    format_json_repair_analysis_case_detail,
    format_json_repair_analysis_summary,
)
from czjLLM.utilities.json_repair_analysis import (
    MAX_ANALYSIS_CHARS, analyze_json_repair, validate_repair_detail,
)
from czjLLM.utilities.processing_quality import (
    QualityAccumulator, emit_quality_event, quality_event_path,
)
from czjLLM.utilities.processing_quality_run_reader import QualityRunTailReader
from czjLLM.utilities.processing_quality_rotation import rotate_quality_event_stream


def _analyze(original, repaired):
    with pytest.raises(json.JSONDecodeError) as exc:
        json.loads(original)
    json.loads(repaired)
    code, metrics = analyze_json_repair(original, repaired, exc.value)
    assert validate_repair_detail(metrics)
    return code, metrics


def test_missing_comma_and_bracket_only_preserve_literal_tokens():
    code, m = _analyze('{"a":1 "b":2}', '{"a":1,"b":2}')
    assert code == "JSON_REPAIR_SYNTAX_CANDIDATE"
    assert m["same_literal_pct"] == 100
    assert m["before_key_patterns"] == m["after_key_patterns"] == 2
    code, m = _analyze('[{"name":"敏感", "score":1}', '[{"name":"敏感", "score":1}]')
    assert code == "JSON_REPAIR_SYNTAX_CANDIDATE"
    assert m["same_literal_pct"] == 100


def test_unterminated_string_tail_has_distinct_unverified_content_warning():
    code, m = _analyze('{"name":"在這裡被切', '{"name":"在這裡被切完"}')
    assert code == "JSON_REPAIR_TAIL_CANDIDATE"
    assert m["error_kind"] == "UNTERMINATED_STRING"
    assert m["error_pos_pct"] < 100  # parser points to starting quote
    assert m["common_prefix_chars"] == m["original_chars"]


def test_changed_content_is_not_mislabeled_as_punctuation_repair():
    code, m = _analyze('{"a":"source" "b":1}', '{"a":"changed","b":1}')
    assert code in {"JSON_REPAIR_CONTENT_EDIT", "JSON_REPAIR_LARGE_CHANGE"}
    assert m["same_literal_pct"] < 100
    code, m = _analyze(
        '{"a":"alpha" "b":"bravo", "c":"charlie"}',
        '{"a":"entirely new text","k":"new data"}',
    )
    assert code == "JSON_REPAIR_LARGE_CHANGE"
    assert m["before_key_patterns"] > m["after_key_patterns"]


def test_bounded_analysis_refuses_huge_input_without_storing_any_payload():
    original = '{"a":"' + ("sensitive" * 18_000)
    repaired = json.dumps({"a": "sensitive" * 18_000}, ensure_ascii=False)
    code, m = _analyze(original, repaired)
    assert len(original) > MAX_ANALYSIS_CHARS
    assert code == "JSON_REPAIR_COMPARISON_UNAVAILABLE"
    assert m["same_literal_pct"] == 0
    assert not any(isinstance(v, str) and "sensitive" in v for v in m.values())


def test_event_reader_gui_aggregates_and_rotates_without_payload(tmp_path):
    audit = tmp_path / "llm_call_audit_run-A.csv"
    original = '{"secret":"此處是私人文字" "v":2}'
    repaired = '{"secret":"此處是私人文字","v":2}'
    code, detail = _analyze(original, repaired)
    emit_quality_event(
        str(audit), run_id="a", event="slice_json_repair_analysis",
        code=code, scope="slice", outcome="observed",
        slice_id=str(tmp_path / "TODO" / "row-sensitive-42.txt"),
        detail=detail,
    )
    event_file = quality_event_path(str(audit))
    event_text = event_file.read_text(encoding="utf-8")
    assert "私人文字" not in event_text
    assert "row-sensitive" in event_text  # pre-existing stream uses basename
    assert "secret" not in event_text
    reader = QualityRunTailReader(str(event_file))
    changed, stats = reader.poll()
    assert changed
    assert stats["repair_analysis_count"] == 1
    assert stats["repair_analysis_categories"][code] == 1
    assert stats["repair_success_pct"] is None  # not a repair-success event
    assert len(stats["repair_analysis_recent"]) == 1
    recent = stats["repair_analysis_recent"][0]
    assert "row-sensitive" not in json.dumps(recent, ensure_ascii=False)
    assert len(recent["slice_hint"]) == 8
    assert "疑似符號修補 1" in format_json_repair_analysis_summary(stats)
    assert format_json_repair_analysis_case(recent)[3].startswith(str(len(original)))
    assert "原始解析錯誤" in format_json_repair_analysis_case_detail(recent)
    assert reader.poll()[0] is False
    rotate_quality_event_stream(audit)
    assert reader.poll()[1]["repair_analysis_count"] == 1
    assert reader.poll()[1]["repair_analysis_recent"] == stats["repair_analysis_recent"]


def test_quality_rejects_payload_injected_via_detail_before_writing_or_counting(tmp_path):
    audit = tmp_path / "llm_call_audit_security.csv"
    code, m = _analyze('{"a":1,}', '{"a":1}')
    with pytest.raises(ValueError, match="scalar detail"):
        emit_quality_event(
            str(audit), event="slice_json_repair_analysis", code=code,
            scope="slice", outcome="observed",
            detail={**m, "raw_output": "secret"},
        )
    assert not quality_event_path(str(audit)).exists()
    acc = QualityAccumulator()
    assert acc.add({
        "schema_version": 1, "event_id": "spoof",
        "event": "slice_json_repair_analysis", "scope": "slice",
        "code": code, "detail": {**m, "raw_output": "secret"},
    }) is False
    assert acc.snapshot()["events"] == 0


def test_real_worker_handler_emits_success_and_comparison_without_payload(
    monkeypatch, tmp_path, capsys,
):
    import czjLLM.prompt_pipeline.pipeline_controller as pc

    audit = tmp_path / "llm_call_audit_live.csv"
    before = '{"confidential":"內部秘密" "count":2}'
    after = '{"confidential":"內部秘密","count":2}'
    monkeypatch.setattr(pc, "json_format_caller", lambda **kw: after)
    worker = pc.PromptAPIPipeline(
        task="to json", content="",
        promptFile=str(tmp_path / "RUNNING" / "row.txt"),
        model_spec={"model_name": "mock-model", "base_url": ["http://invalid.local"]},
        audit_run_id="this-run", audit_path=str(audit),
    )
    monkeypatch.setattr(
        worker, "extract_MainFileName_and_input_text",
        lambda: ("", "", ""),
    )
    retry, result = worker.handle_json_output(before)
    assert retry == [] and result == after
    text = capsys.readouterr().out
    assert "內部秘密" not in text
    records = [
        json.loads(line)
        for line in quality_event_path(str(audit)).read_text(encoding="utf-8").splitlines()
    ]
    assert [r["event"] for r in records] == [
        "slice_json_validation", "slice_json_repair",
        "slice_json_repair_analysis",
    ]
    acc = QualityAccumulator()
    for record in records:
        assert acc.add(record)
    snap = acc.snapshot()
    assert snap["slice_initial_invalid"] == 1
    assert snap["repair_succeeded"] == 1
    assert snap["repair_analysis_count"] == 1


def test_gui_wiring_has_live_toggle_and_bounded_case_list():
    gui = Path("czjLLM/job_manager/win_gui.py").read_text(encoding="utf-8")
    assert 'repair_analysis_section = ttk.Frame(quality_section)' in gui
    assert 'repair_analysis_frame.pack_forget()' in gui
    assert '_refresh_repair_analysis()' in gui
    assert '(_quality_stats.get("repair_analysis_recent") or [])[:12]' in gui
    assert 'repair_analysis_tree.bind("<<TreeviewSelect>>"' in gui
    assert "JSON 修復前後" in gui
    assert "字面值相同率" in gui
