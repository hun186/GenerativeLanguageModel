import json
import sys
import types
from types import SimpleNamespace


class _OpenCC:
    def __init__(self, *args, **kwargs):
        pass

    def convert(self, text):
        return text


sys.modules.setdefault("opencc", types.SimpleNamespace(OpenCC=_OpenCC))
sys.modules.setdefault("json_repair", types.SimpleNamespace(repair_json=lambda text, **kwargs: text))

import czjLLM.utilities.combine_utils as combine_utils
from czjLLM.utilities.combine_utils import (
    _should_parse_as_json_task,
    combine_api_finished_item,
)


def _oswalk(path):
    return [str(p) for p in sorted(__import__("pathlib").Path(path).rglob("*")) if p.is_file()]


combine_utils.OSWALK = _oswalk


def _build_ctx(tmp_path, *, task: str, merge_slices: bool):
    prompt_root = tmp_path / "PromptRoot"
    finished_root = tmp_path / "Finished"
    prompt_root.mkdir(parents=True, exist_ok=True)
    finished_root.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        task=task,
        prompt_dir=str(prompt_root),
        temp_txt_finished_dir=str(finished_root),
        llm_source_finished_dir=str(finished_root),
        llm_source_dir=str(tmp_path / "Source"),
        debug=True,
        merge_slices=merge_slices,
        merge_conflict_policy="prefer_left",
        merge_dedup_lists=True,
        merge_log_changes=False,
        merge_max_log=10,
        PGMSubDir=str(tmp_path),
    )


def test_json_slices_concat_into_single_list_when_merge_disabled(tmp_path):
    ctx = _build_ctx(tmp_path, task="to json format", merge_slices=False)
    item = tmp_path / "PromptRoot" / "jobA"
    suc = item / "Success"
    suc.mkdir(parents=True, exist_ok=True)
    (suc / "0.txt").write_text(json.dumps([{"id": 1}, {"id": 2}], ensure_ascii=False), encoding="utf-8")
    (suc / "1.txt").write_text(json.dumps([{"id": 3}], ensure_ascii=False), encoding="utf-8")

    out = combine_api_finished_item(str(item), ctx)
    data = json.loads(open(out, "r", encoding="utf-8").read())
    assert isinstance(data, list)
    assert [x["id"] for x in data] == [1, 2, 3]


def test_json_slices_merge_dicts_when_merge_enabled(tmp_path):
    ctx = _build_ctx(tmp_path, task="to json format", merge_slices=True)
    item = tmp_path / "PromptRoot" / "jobB"
    suc = item / "Success"
    suc.mkdir(parents=True, exist_ok=True)
    (suc / "0.txt").write_text(json.dumps([{"title": "A", "score": 1}], ensure_ascii=False), encoding="utf-8")
    (suc / "1.txt").write_text(json.dumps([{"title": "B", "extra": 2}], ensure_ascii=False), encoding="utf-8")

    out = combine_api_finished_item(str(item), ctx)
    data = json.loads(open(out, "r", encoding="utf-8").read())
    assert isinstance(data, dict)
    # prefer_left：同 key 衝突保留較早切片值
    assert data["title"] == "A"
    assert data["score"] == 1
    assert data["extra"] == 2


def test_combiner_uses_actual_combined_consumer_not_primary_stage_profile(tmp_path):
    from czjLLM.es_mode.output_profiles.multidim_event import (
        normalize_multidim_event_payload,
    )

    ctx = _build_ctx(tmp_path, task="to json format", merge_slices=True)
    ctx.output_col = "generic_json"
    ctx.output_profile = "none"
    ctx.es_writeback_rules = [
        {"output_col": "generic_json", "source": "stage",
         "stage": "extract", "output_profile": "none"},
        # Missing profile: ESSink infers strict multi-dimensional Event JSON.
        {"output_col": "multidim_event_json", "source": "combined"},
    ]
    item = tmp_path / "PromptRoot" / "different-source-contracts"
    suc = item / "Success"
    suc.mkdir(parents=True, exist_ok=True)
    for i, action in enumerate(("first", "second")):
        obj = {
            "article_title": "Two slice test",
            "article_date_iso": "2020-01-01",
            "article_date_precision": "year",
            "Event": [{
                "event_id": "E1", "action": action, "time_raw": "2020",
                "time_iso": "2020-01-01", "time_precision": "year",
            }],
            "Person": [{"event_ids": ["E1"], "name": action}],
        }
        (suc / f"{i}.txt").write_text(
            json.dumps([obj], ensure_ascii=False), encoding="utf-8",
        )
    out = combine_api_finished_item(str(item), ctx)
    merged = json.loads(open(out, "r", encoding="utf-8").read())
    # Combined is a dict at the compatibility boundary. Row Merger wraps it
    # into an ES article array for the combined-source strict destination.
    assert isinstance(merged, dict)
    validated = normalize_multidim_event_payload([merged])
    assert [event["event_id"] for event in validated[0]["Event"]] == ["E1", "E2"]
    assert [person["event_ids"] for person in validated[0]["Person"]] == [
        ["E1"], ["E2"],
    ]


def test_invalid_local_event_links_report_one_concise_schema_error(tmp_path, capsys):
    import pytest
    from czjLLM.utilities.slice_merge import MultidimEventReferenceError

    ctx = _build_ctx(tmp_path, task="to json format", merge_slices=True)
    ctx.output_col = "multidim_event_json"
    ctx.output_profile = "multidim_event"
    item = tmp_path / "PromptRoot" / "invalid-event-link"
    success = item / "Success"
    success.mkdir(parents=True, exist_ok=True)
    good = {
        "Event": [{"event_id": "E1"}],
        "Person": [{"name": "A", "event_ids": ["E1"]}],
    }
    bad = {
        "Event": [{"event_id": "E1"}],
        "evidence_snippets": [{"text": "a citation", "event_ids": ["T1"]}],
    }
    for index, fragment in enumerate((good, bad)):
        (success / f"{index}.txt").write_text(
            json.dumps([fragment], ensure_ascii=False), encoding="utf-8",
        )
    with pytest.raises(MultidimEventReferenceError, match="missing local Event.event_id 'T1'"):
        combine_api_finished_item(str(item), ctx)
    output = capsys.readouterr().out
    assert output.count("[COMBINE-SCHEMA]") == 1
    assert "missing local Event.event_id 'T1'" in output
    assert "[COMBINE-FATAL]" not in output
    assert "Traceback (most recent call last)" not in output
    assert [x.name for x in sorted(success.glob("*.txt"))] == ["0.txt", "1.txt"]


def test_bad_score_in_later_chunk_stops_real_combiner_without_console_storm(
    tmp_path, capsys,
):
    import pytest
    from czjLLM.utilities.slice_merge import MultidimEventSchemaError

    ctx = _build_ctx(tmp_path, task="to json format", merge_slices=True)
    ctx.output_col = "multidim_event_json"
    ctx.output_profile = "multidim_event"
    item = tmp_path / "PromptRoot" / "invalid-flat-score"
    success = item / "Success"
    success.mkdir(parents=True, exist_ok=True)
    for index, score in enumerate((85, True)):
        fragment = {
            "article_date_iso": None,
            "article_date_precision": "unknown",
            "coverage": score,
            "Event": [{
                "event_id": "E1", "time_raw": None,
                "time_iso": None, "time_precision": "unknown",
            }],
        }
        (success / f"{index}.txt").write_text(
            json.dumps([fragment], ensure_ascii=False), encoding="utf-8",
        )
    with pytest.raises(MultidimEventSchemaError, match="slice 1 article.coverage"):
        combine_api_finished_item(str(item), ctx)
    output = capsys.readouterr().out
    assert output.count("[COMBINE-SCHEMA]") == 1
    assert "[COMBINE-FATAL]" not in output
    assert "Traceback (most recent call last)" not in output
    assert [x.name for x in sorted(success.glob("*.txt"))] == ["0.txt", "1.txt"]


def test_json_mode_ignores_blank_success_files_and_returns_empty_array(tmp_path):
    ctx = _build_ctx(tmp_path, task="to json format", merge_slices=False)
    item = tmp_path / "PromptRoot" / "jobC"
    suc = item / "Success"
    suc.mkdir(parents=True, exist_ok=True)
    (suc / "0.txt").write_text("", encoding="utf-8")
    (suc / "1.txt").write_text("   \n", encoding="utf-8")

    out = combine_api_finished_item(str(item), ctx)
    assert open(out, "r", encoding="utf-8").read().strip() == "[]"


def test_json_single_slice_list_preserved_when_merge_enabled(tmp_path):
    ctx = _build_ctx(tmp_path, task="to json format", merge_slices=True)
    item = tmp_path / "PromptRoot" / "jobD"
    suc = item / "Success"
    suc.mkdir(parents=True, exist_ok=True)
    (suc / "0.txt").write_text(
        json.dumps(
            [
                {"inputName": "海巡署", "formalName": "中華民國行政院海巡署"},
                {"inputName": "警政署", "formalName": "中華民國行政院警政署"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    out = combine_api_finished_item(str(item), ctx)
    data = json.loads(open(out, "r", encoding="utf-8").read())
    assert isinstance(data, list)
    assert [x["inputName"] for x in data] == ["海巡署", "警政署"]


def test_combine_step_checkpoints_are_quiet_by_default(tmp_path, capsys):
    ctx = _build_ctx(tmp_path, task="to json format", merge_slices=False)
    ctx.combine_debug = False
    item = tmp_path / "PromptRoot" / "jobQuiet"
    suc = item / "Success"
    suc.mkdir(parents=True, exist_ok=True)
    (suc / "0.txt").write_text(json.dumps([{"id": 1}], ensure_ascii=False), encoding="utf-8")

    out = combine_api_finished_item(str(item), ctx)
    captured = capsys.readouterr()
    assert out
    assert "[combine-step]" not in captured.out
    assert "CombBackFN" in captured.out


def test_combine_step_debug_can_be_enabled_by_yaml_flag(tmp_path, capsys):
    ctx = _build_ctx(tmp_path, task="to json format", merge_slices=False)
    ctx.combine_debug = True
    item = tmp_path / "PromptRoot" / "jobVerbose"
    suc = item / "Success"
    suc.mkdir(parents=True, exist_ok=True)
    (suc / "0.txt").write_text(json.dumps([{"id": 1}], ensure_ascii=False), encoding="utf-8")

    combine_api_finished_item(str(item), ctx)
    captured = capsys.readouterr()
    assert "[combine-step]" in captured.out
    assert "CombBackFN" in captured.out


def _write_success(item, name, text):
    success = item / "Success"
    success.mkdir(parents=True, exist_ok=True)
    (success / name).write_text(text, encoding="utf-8")


def _read_combined(path):
    return __import__("pathlib").Path(path).read_text(encoding="utf-8")


def test_text_combine_freezes_lexical_order_newlines_and_mirrored_output_path(tmp_path):
    ctx = _build_ctx(tmp_path, task="plain summary", merge_slices=False)
    item = tmp_path / "PromptRoot" / "nested" / "article"
    _write_success(item, "2.txt", "CCC")
    _write_success(item, "10.txt", "BBB\n")
    _write_success(item, "1.txt", "AAA")

    out = combine_api_finished_item(str(item), ctx)

    assert __import__("pathlib").Path(out) == (
        tmp_path / "Finished" / "nested" / "article_plain_summary.txt"
    )
    assert _read_combined(out) == "AAA\nBBB\nCCC\n"


def test_text_combine_skips_empty_and_no_topic_slices(tmp_path):
    ctx = _build_ctx(tmp_path, task="plain summary", merge_slices=False)
    item = tmp_path / "PromptRoot" / "article"
    _write_success(item, "0.txt", "")
    _write_success(item, "1.txt", "  \n")
    _write_success(item, "2.txt", "無主題相關內容：略過這個切片")
    _write_success(item, "3.txt", "kept")

    assert _read_combined(combine_api_finished_item(str(item), ctx)) == "kept\n"


def test_text_combine_all_empty_slices_produce_empty_file(tmp_path):
    ctx = _build_ctx(tmp_path, task="plain summary", merge_slices=False)
    item = tmp_path / "PromptRoot" / "article"
    _write_success(item, "0.txt", "")
    _write_success(item, "1.txt", "\n\t")

    assert _read_combined(combine_api_finished_item(str(item), ctx)) == ""


def test_json_single_dict_and_single_list_share_legacy_list_envelope(tmp_path):
    ctx = _build_ctx(tmp_path, task="return json", merge_slices=True)
    dict_item = tmp_path / "PromptRoot" / "dict"
    list_item = tmp_path / "PromptRoot" / "list"
    _write_success(dict_item, "0.txt", '{"id": 1}')
    _write_success(list_item, "0.txt", '[{"id": 2}, {"id": 3}]')

    assert json.loads(_read_combined(combine_api_finished_item(str(dict_item), ctx))) == [{"id": 1}]
    assert json.loads(_read_combined(combine_api_finished_item(str(list_item), ctx))) == [
        {"id": 2}, {"id": 3}
    ]


def test_json_concat_is_one_level_and_discards_non_dict_list_members(tmp_path):
    ctx = _build_ctx(tmp_path, task="return json", merge_slices=False)
    item = tmp_path / "PromptRoot" / "one-level"
    _write_success(item, "0.txt", '[[{"nested": 0}], {"id": 1}, 9]')
    _write_success(item, "1.txt", '[{"id": 2}]')

    data = json.loads(_read_combined(combine_api_finished_item(str(item), ctx)))

    assert data == [{"id": 1}, {"id": 2}]


def test_json_mixed_dict_and_list_slices_preserve_file_order(tmp_path):
    ctx = _build_ctx(tmp_path, task="return json", merge_slices=False)
    item = tmp_path / "PromptRoot" / "mixed-shapes"
    _write_success(item, "0.txt", '{"id": 1}')
    _write_success(item, "1.txt", '[{"id": 2}, {"id": 3}]')

    assert json.loads(_read_combined(combine_api_finished_item(str(item), ctx))) == [
        {"id": 1}, {"id": 2}, {"id": 3}
    ]


def test_json_malformed_only_falls_back_to_exact_text_for_return_json(tmp_path, capsys):
    ctx = _build_ctx(tmp_path, task="return json", merge_slices=False)
    item = tmp_path / "PromptRoot" / "malformed"
    _write_success(item, "0.txt", '{"broken":')
    _write_success(item, "1.txt", "not-json\n")

    result = _read_combined(combine_api_finished_item(str(item), ctx))

    assert result == '{"broken":\nnot-json\n'
    assert "將以純文字串接回退" in capsys.readouterr().out


def test_json_mixed_valid_and_malformed_silently_keeps_only_valid_rows(tmp_path):
    ctx = _build_ctx(tmp_path, task="return json", merge_slices=False)
    item = tmp_path / "PromptRoot" / "partially-malformed"
    _write_success(item, "0.txt", '[{"id": 1}]')
    _write_success(item, "1.txt", "not-json")

    assert json.loads(_read_combined(combine_api_finished_item(str(item), ctx))) == [{"id": 1}]


def test_multistage_malformed_json_changes_warning_not_combined_artifact(tmp_path, capsys):
    ctx = _build_ctx(tmp_path, task="return json", merge_slices=False)
    ctx.stages = [{"name": "extract"}, {"name": "summarize"}]
    item = tmp_path / "PromptRoot" / "multistage-malformed"
    _write_success(item, "0.txt", "not-json")

    assert _read_combined(combine_api_finished_item(str(item), ctx)) == "not-json\n"
    assert "multistage 將改由 stage 輸出寫回" in capsys.readouterr().out


def test_json_task_detection_freezes_positive_and_negative_hints():
    for hint in ("output json", "return json", "請回傳JSON"):
        assert _should_parse_as_json_task(hint) is True
    for hint in ("禁止輸出 JSON", "不要輸出 JSON", "do not output json", "without json"):
        assert _should_parse_as_json_task(hint) is False
