import json
from types import SimpleNamespace

from czjLLM.utilities.combine_utils import combine_api_finished_item


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
