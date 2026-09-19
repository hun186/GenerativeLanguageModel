import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


class _OpenCC:
    def __init__(self, *args, **kwargs):
        pass

    def convert(self, text):
        return text


sys.modules.setdefault("opencc", types.SimpleNamespace(OpenCC=_OpenCC))
sys.modules.setdefault(
    "json_repair", types.SimpleNamespace(repair_json=lambda text, **kwargs: text)
)

import czjLLM.utilities.combine_utils as combine_utils
from czjLLM.reduction.config import parse_reduction_config
from czjLLM.reduction.engine import reduce_single_pass


combine_utils.OSWALK = lambda path: [
    str(p) for p in sorted(Path(path).rglob("*")) if p.is_file()
]


def _ctx(tmp_path, reduction_marker=...):
    prompt_root = tmp_path / "Prompt"
    finished_root = tmp_path / "Finished"
    prompt_root.mkdir(exist_ok=True)
    finished_root.mkdir(exist_ok=True)
    values = dict(
        task="plain summary",
        prompt_dir=str(prompt_root),
        temp_txt_finished_dir=str(finished_root),
        llm_source_finished_dir=str(finished_root),
        llm_source_dir=str(tmp_path / "Source"),
        debug=True,
        merge_slices=False,
        PGMSubDir=str(tmp_path),
    )
    if reduction_marker is not ...:
        values["reduction"] = reduction_marker
    return SimpleNamespace(**values)


def _write(item, name, payload):
    success = item / "Success"
    success.mkdir(parents=True, exist_ok=True)
    (success / name).write_text(payload, encoding="utf-8")


def _read_output(item, ctx):
    return Path(combine_utils.combine_api_finished_item(str(item), ctx)).read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize("reduction_marker", [..., {"enabled": False, "profile": "concat_text"}])
def test_routing_off_never_invokes_reduction_facade(
    tmp_path, monkeypatch, reduction_marker
):
    ctx = _ctx(tmp_path, reduction_marker)
    item = Path(ctx.prompt_dir) / "legacy"
    _write(item, "1.txt", "first")
    _write(item, "2.txt", "second")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Reduction facade must be bypassed")

    monkeypatch.setattr(combine_utils, "reduce_single_pass", fail_if_called)

    assert _read_output(item, ctx) == "first\nsecond\n"


def test_explicit_concat_text_routes_once_with_prepared_ordered_chunks(
    tmp_path, monkeypatch, capsys
):
    ctx = _ctx(
        tmp_path,
        {"enabled": True, "profile": "concat_text", "controller": "single_pass"},
    )
    item = Path(ctx.prompt_dir) / "text"
    _write(item, "10.txt", "second")
    _write(item, "2.txt", "first\n")
    original = combine_utils.reduce_single_pass
    calls = []

    def spy(items, config, **kwargs):
        calls.append(list(items))
        return original(calls[-1], config, **kwargs)

    monkeypatch.setattr(combine_utils, "reduce_single_pass", spy)

    assert _read_output(item, ctx) == "second\nfirst\n"
    assert calls == [["second\n", "first\n"]]
    assert "[reduction] enabled=true controller=single_pass profile=concat_text" in capsys.readouterr().out


def test_explicit_concat_json_list_preserves_one_level_order(tmp_path):
    ctx = _ctx(tmp_path, {"enabled": True, "profile": "concat_json_list"})
    item = Path(ctx.prompt_dir) / "json-list"
    _write(item, "0.txt", '[[{"nested": 0}], {"id": 1}, 9]')
    _write(item, "1.txt", '{"id": 2}')

    assert json.loads(_read_output(item, ctx)) == [{"id": 1}, {"id": 2}]


def test_explicit_deep_merge_runs_once_and_uses_combine_dedup_default(
    tmp_path, monkeypatch
):
    ctx = _ctx(tmp_path, {"enabled": True, "profile": "legacy_json_deep_merge"})
    item = Path(ctx.prompt_dir) / "deep"
    _write(item, "0.txt", '{"values": [1], "title": "left"}')
    _write(item, "1.txt", '{"values": [1, 2], "title": "right"}')
    original = combine_utils.reduce_single_pass
    call_count = 0

    def spy(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(combine_utils, "reduce_single_pass", spy)

    assert json.loads(_read_output(item, ctx)) == {
        "values": [1, 2],
        "title": "left",
    }
    assert call_count == 1


def test_deep_merge_explicit_options_map_to_reducer():
    items = [
        {"values": [1], "title": "short"},
        {"values": [1], "title": "a much longer title"},
    ]

    no_dedup = reduce_single_pass(
        items,
        parse_reduction_config(
            {
                "enabled": True,
                "profile": "legacy_json_deep_merge",
                "options": {"dedup_lists": False, "conflict_policy": "prefer_right"},
            }
        ),
    )
    longer = reduce_single_pass(
        items,
        parse_reduction_config(
            {
                "enabled": True,
                "profile": "legacy_json_deep_merge",
                "options": {"conflict_policy": "longer_str"},
            }
        ),
    )
    non_empty = reduce_single_pass(
        [{"title": ""}, {"title": "right"}],
        parse_reduction_config(
            {
                "enabled": True,
                "profile": "legacy_json_deep_merge",
                "options": {"conflict_policy": "non_empty"},
            }
        ),
    )

    assert no_dedup.payload == {"values": [1, 1], "title": "a much longer title"}
    assert longer.payload["title"] == "a much longer title"
    assert non_empty.payload["title"] == "right"
    assert no_dedup.audit["counts"]["list_dedup_removed"] == 0
