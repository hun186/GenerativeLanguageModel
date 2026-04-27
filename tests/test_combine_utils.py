from pathlib import Path

from czjLLM.utilities.combine_utils import combine_api_finished_item


class _Ctx:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def test_combine_api_finished_item_skips_json_repair_for_route_like_output(tmp_path: Path):
    prompt_root = tmp_path / "prompt"
    item_dir = prompt_root / "cache" / "row_1"
    success_dir = item_dir / "Success"
    success_dir.mkdir(parents=True)
    (success_dir / "0.txt").write_text("org\n", encoding="utf-8")

    out_root = tmp_path / "finished"
    ctx = _Ctx(
        task="route_Organization Profile Analyzer to json format",
        prompt_dir=str(prompt_root),
        llm_source_finished_dir=str(out_root),
        debug=True,
    )

    out_fn = combine_api_finished_item(str(item_dir), ctx)
    assert Path(out_fn).is_file()
    assert Path(out_fn).read_text(encoding="utf-8").strip() == "org"


def test_combine_api_finished_item_keeps_json_merge_for_json_chunks(tmp_path: Path):
    prompt_root = tmp_path / "prompt"
    item_dir = prompt_root / "cache" / "row_2"
    success_dir = item_dir / "Success"
    success_dir.mkdir(parents=True)
    (success_dir / "0.txt").write_text('[{"route":"org","inputName":"A"}]\n', encoding="utf-8")

    out_root = tmp_path / "finished"
    ctx = _Ctx(
        task="Organization Profile Analyzer to json format",
        prompt_dir=str(prompt_root),
        llm_source_finished_dir=str(out_root),
        debug=True,
    )

    out_fn = combine_api_finished_item(str(item_dir), ctx)
    text = Path(out_fn).read_text(encoding="utf-8")
    assert '"route": "org"' in text
    assert '"inputName": "A"' in text


def test_combine_api_finished_item_skips_json_merge_for_mixed_json_and_plain_chunks(tmp_path: Path):
    prompt_root = tmp_path / "prompt"
    item_dir = prompt_root / "cache" / "row_3"
    success_dir = item_dir / "Success"
    success_dir.mkdir(parents=True)
    (success_dir / "0.txt").write_text('[{"route":"org"}]\n', encoding="utf-8")
    (success_dir / "1.txt").write_text("other\n", encoding="utf-8")

    out_root = tmp_path / "finished"
    ctx = _Ctx(
        task="any task name",
        prompt_dir=str(prompt_root),
        llm_source_finished_dir=str(out_root),
        debug=True,
    )

    out_fn = combine_api_finished_item(str(item_dir), ctx)
    text = Path(out_fn).read_text(encoding="utf-8")
    assert '[\n  {\n    "route": "org"\n  }\n]\nother' in text


def test_combine_api_finished_item_does_not_treat_non_json_fence_as_json(tmp_path: Path):
    prompt_root = tmp_path / "prompt"
    item_dir = prompt_root / "cache" / "row_4"
    success_dir = item_dir / "Success"
    success_dir.mkdir(parents=True)
    (success_dir / "0.txt").write_text("```python\nprint('hi')\n```\n", encoding="utf-8")

    out_root = tmp_path / "finished"
    ctx = _Ctx(
        task="any task",
        prompt_dir=str(prompt_root),
        llm_source_finished_dir=str(out_root),
        debug=True,
    )

    out_fn = combine_api_finished_item(str(item_dir), ctx)
    text = Path(out_fn).read_text(encoding="utf-8")
    assert "```python" in text
    assert "print('hi')" in text
