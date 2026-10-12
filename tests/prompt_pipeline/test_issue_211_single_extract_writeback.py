"""Issue #211: one-extract-stage SQL/Excel JSON slice writeback regression."""

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from czjLLM.prompt_pipeline.pipeline_controller import (
    _merge_single_extract_stage_json_parts,
    _require_complete_single_extract_stage,
    _single_extract_stage_writeback_enabled,
    process_prompt_and_merge_multistage,
)
from czjLLM.sql_mode.runtime.row_merger_generic import (
    _build_writeback_values, _resolve_flatten_targets,
)


_CONFIGS = (
    "excel_json_singlestage_in_multistage.yaml",
    "sqlite_json_singlestage_in_multistage.yaml",
)


def _config(name):
    path = Path("czjLLM/yaml") / name
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _ctx(config, finished):
    return SimpleNamespace(
        merge_slices=config["merge_slices"],
        merge_conflict_policy="prefer_left",
        merge_dedup_lists=False,
        merge_log_changes=False,
        output_col=config["output_col"],
        sql_writeback_rules=config["sql_writeback_rules"],
        sql_flatten_writeback_rules=config["sql_flatten_writeback_rules"],
        flatten_json_output=True,
        save_raw_input_when_flatten=True,
        temp_txt_finished_dir=str(finished),
        manifest_lookup_attempts=1,
        manifest_lookup_sleep_ms=0,
    )


def _write_manifest_and_stage(finished, source, result_text):
    directory = finished / "_stage_merges" / source
    directory.mkdir(parents=True)
    stage_name = "01_extract.txt"
    (directory / stage_name).write_text(result_text, encoding="utf-8")
    (directory / "manifest.json").write_text(json.dumps({
        "source": source,
        "stages": [{"name": "extract", "merged": True,
                    "merged_file": stage_name, "pieces": 2}],
    }), encoding="utf-8")
    combined = directory / f"{source}_multistage_combined.txt"
    combined.write_text(result_text, encoding="utf-8")
    return combined


@pytest.mark.parametrize("filename", _CONFIGS)
def test_multiple_slices_reach_one_valid_json_writeback_and_flatten(filename, tmp_path):
    config = _config(filename)
    assert len(config["stages"]) == 1
    assert config["stages"][0]["name"] == "extract"
    assert config["sql_writeback_rules"][0]["source"] == "stage"
    assert config["sql_writeback_rules"][0]["stage"] == "extract"

    ctx = _ctx(config, tmp_path / "finished")
    slices = [
        json.dumps([{"inputName": "Alpha", "keyFunctions": ["first"]}]),
        json.dumps([{"formalName": "Alpha Org", "keyFunctions": ["second"]}]),
    ]
    with pytest.raises(json.JSONDecodeError):
        json.loads("\n".join(slices))  # Prior stage artifact was invalid JSON.

    stage_text = _merge_single_extract_stage_json_parts(slices, ctx)
    expected = {
        "inputName": "Alpha", "formalName": "Alpha Org",
        "keyFunctions": ["first", "second"],
    }
    assert json.loads(stage_text) == expected

    combined = _write_manifest_and_stage(tmp_path / "finished", "row211", stage_text)
    write_map, flatten_source, source_logs, write_sources = _build_writeback_values(
        ctx, str(combined), combined.read_text(encoding="utf-8"),
    )
    assert json.loads(write_map["File_result"]) == expected
    assert json.loads(flatten_source) == expected
    assert write_sources == {"File_result": "stage:extract"}
    assert "File_result<-stage:extract" in source_logs
    targets = _resolve_flatten_targets(ctx, write_map, flatten_source)
    assert len(targets) == 1
    assert targets[0]["output_col"] == "File_result"
    assert json.loads(targets[0]["source_text"]) == expected
    assert "formalName" in targets[0]["allowed_fields"]


def test_single_slice_list_envelope_is_preserved_without_double_merge():
    ctx = SimpleNamespace(merge_conflict_policy="prefer_left", merge_log_changes=False)
    text = '[{"inputName":"Alpha"},{"inputName":"Beta"}]'
    assert _merge_single_extract_stage_json_parts([text], ctx) == text
    assert len(json.loads(_merge_single_extract_stage_json_parts([text], ctx))) == 2


def test_empty_valid_lists_are_json_not_newline_concatenation():
    ctx = SimpleNamespace(merge_log_changes=False)
    assert json.loads(_merge_single_extract_stage_json_parts(["[]", "[]"], ctx)) == []


@pytest.mark.parametrize("slices", [
    ['{"inputName":"ok"}', '{"broken":'],
    ['{"inputName":"ok"}', '"unsupported scalar"'],
    ['{"inputName":"ok"}', '[{"good":1}, "bad"]'],
    ['{"inputName":"ok"}', ''],
    ['{"inputName":"ok"}', None],
    ['not valid'],
    [],
])
def test_invalid_or_partial_stage_json_fails_before_manifest_write(slices):
    with pytest.raises(ValueError, match="extract stage JSON slice"):
        _merge_single_extract_stage_json_parts(slices, SimpleNamespace())


def test_stage_merge_wiring_is_narrow_to_single_extract_stage():
    source = inspect.getsource(process_prompt_and_merge_multistage)
    assert "_single_extract_stage_writeback_enabled(stage_defs, ctx)" in source
    assert "_require_complete_single_extract_stage(" in source
    assert "expected_extract_files[job.chunk_id]" in source
    assert "if single_extract_stage_writeback and stage.name" in source
    assert "_merge_single_extract_stage_json_parts(merged_parts, ctx)" in source
    assert 'stage_text = "\\n".join(merged_parts)' in source
    assert 'f.write(stage_text)' in source


@pytest.mark.parametrize("filename", _CONFIGS)
def test_issue_211_guard_only_applies_to_single_extract_json_writeback(filename):
    cfg = _config(filename)
    ctx = _ctx(cfg, Path("unused"))
    stages = [SimpleNamespace(name="extract")]
    assert _single_extract_stage_writeback_enabled(stages, ctx)
    assert not _single_extract_stage_writeback_enabled([*stages, SimpleNamespace(name="route")], ctx)
    assert not _single_extract_stage_writeback_enabled([SimpleNamespace(name="route")], ctx)
    ctx.merge_slices = False
    assert not _single_extract_stage_writeback_enabled(stages, ctx)
    ctx.merge_slices = True
    ctx.sql_writeback_rules = [{"output_col": "File_result", "source": "combined"}]
    assert not _single_extract_stage_writeback_enabled(stages, ctx)


def _stage_success(item, files):
    folder = item / "_stage_outputs" / "extract"
    folder.mkdir(parents=True)
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8")


def test_all_stage_chunks_and_exact_snapshot_names_required_before_writeback(tmp_path):
    first, second = tmp_path / "row_first", tmp_path / "row_second"
    _stage_success(first, {"0.txt": '{"keyFunctions":["A"]}'})
    _stage_success(second, {"0.txt": '{"keyFunctions":["B"]}'})
    runtime = {
        str(first): SimpleNamespace(stages={"extract": SimpleNamespace(state="success")}),
        str(second): SimpleNamespace(stages={"extract": SimpleNamespace(state="success")}),
    }
    items = [str(first), str(second)]
    expected = {str(first): ("0.txt",), str(second): ("0.txt",)}
    complete = {"final": {"finished_chunks": 2}}
    _require_complete_single_extract_stage(complete, runtime, items, expected)

    with pytest.raises(RuntimeError, match="not every input unit finished"):
        _require_complete_single_extract_stage({"final": {"finished_chunks": 1}}, runtime, items, expected)
    runtime[str(second)].stages["extract"].state = "error"
    with pytest.raises(RuntimeError, match="input unit failed"):
        _require_complete_single_extract_stage(complete, runtime, items, expected)
    runtime[str(second)].stages["extract"].state = "success"

    (second / "_stage_outputs" / "extract" / "0.txt").unlink()
    with pytest.raises(RuntimeError, match="missing or mismatched slice snapshots"):
        _require_complete_single_extract_stage(complete, runtime, items, expected)
    _stage_success(second, {"0.txt": '{"keyFunctions":["B"]}', "unexpected.txt": "{}"})
    with pytest.raises(RuntimeError, match="missing or mismatched slice snapshots"):
        _require_complete_single_extract_stage(complete, runtime, items, expected)
    with pytest.raises(RuntimeError, match="missing or mismatched slice snapshots"):
        _require_complete_single_extract_stage(complete, runtime, items, {str(first): ()})


def test_empty_stage_runtime_fails_closed(tmp_path):
    with pytest.raises(RuntimeError, match="not every input unit finished"):
        _require_complete_single_extract_stage({"final": {"finished_chunks": 0}}, {}, [], {})
