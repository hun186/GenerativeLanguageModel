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
from czjLLM.utilities.combine_utils import combine_api_finished_item


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
