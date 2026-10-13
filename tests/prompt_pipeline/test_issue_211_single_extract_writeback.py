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
    _expected_single_extract_slice_files,
    _single_extract_stage_writeback_enabled,
    process_prompt_and_merge_multistage,
)
from czjLLM.sql_mode.runtime.row_merger_generic import (
    _build_writeback_values, _resolve_flatten_targets,
)
from czjLLM.prompt_pipeline.slice_identity import (
    digest_text, install_split_prompts, reconcile_split_transitions,
    record_success_identity, record_split_identity, resolve_success_leaves,
    valid_success,
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
    assert "_expected_single_extract_slice_files(prompt_items)" in source
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
    folder = item / "Success"
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8")
        record_success_identity(
            str(item / "TODO" / name), str(folder / name), "prompt:" + name, text,
        )


def _expected(item, names):
    return {str(item): {name: digest_text("prompt:" + name) for name in names}}


def test_all_stage_chunks_and_exact_snapshot_names_required_before_writeback(tmp_path):
    first, second = tmp_path / "row_first", tmp_path / "row_second"
    _stage_success(first, {"0.txt": '{"keyFunctions":["A"]}'})
    _stage_success(second, {"0.txt": '{"keyFunctions":["B"]}'})
    runtime = {
        str(first): SimpleNamespace(stages={"extract": SimpleNamespace(state="success")}),
        str(second): SimpleNamespace(stages={"extract": SimpleNamespace(state="success")}),
    }
    items = [str(first), str(second)]
    expected = {**_expected(first, ["0.txt"]), **_expected(second, ["0.txt"])}
    complete = {"final": {"finished_chunks": 2}}
    _require_complete_single_extract_stage(complete, runtime, items, expected)

    with pytest.raises(RuntimeError, match="not every input unit finished"):
        _require_complete_single_extract_stage({"final": {"finished_chunks": 1}}, runtime, items, expected)
    runtime[str(second)].stages["extract"].state = "error"
    with pytest.raises(RuntimeError, match="input unit failed"):
        _require_complete_single_extract_stage(complete, runtime, items, expected)
    runtime[str(second)].stages["extract"].state = "success"

    (second / "Success" / "0.txt").unlink()
    with pytest.raises(RuntimeError, match="missing or mismatched Success slice coverage"):
        _require_complete_single_extract_stage(complete, runtime, items, expected)
    _stage_success(second, {"0.txt": '{"keyFunctions":["B"]}', "unexpected.txt": "{}"})
    _require_complete_single_extract_stage(complete, runtime, items, expected)
    assert [fp.name for fp in (second / "_stage_outputs" / "extract").glob("*.txt")] == ["0.txt"]
    with pytest.raises(RuntimeError, match="missing expected current input slices"):
        _require_complete_single_extract_stage(complete, runtime, items, {str(first): {}})


def test_empty_stage_runtime_fails_closed(tmp_path):
    with pytest.raises(RuntimeError, match="not every input unit finished"):
        _require_complete_single_extract_stage({"final": {"finished_chunks": 0}}, {}, [], {})


def test_resume_collects_retained_and_new_slices_before_todo_pruning(tmp_path):
    item = tmp_path / "row_resume"
    (item / "TODO").mkdir(parents=True)
    _stage_success(item, {
        "0.txt": json.dumps({"inputName": "Prior", "keyFunctions": ["old"]}),
    })
    (item / "TODO" / "0.txt").write_text("prompt:0.txt", encoding="utf-8")
    (item / "TODO" / "1.txt").write_text("prompt:1.txt", encoding="utf-8")
    expected = _expected_single_extract_slice_files([str(item)])
    assert tuple(expected[str(item)]) == ("0.txt", "1.txt")

    # Both resume and smart_reset will skip previously completed TODO 0.txt.
    (item / "TODO" / "0.txt").unlink()
    _stage_success(item, {
        "1.txt": json.dumps({"formalName": "Completed", "keyFunctions": ["new"]}),
    })
    # The old delta snapshot contains only the new slice, missing 0.txt.
    snapshot = item / "_stage_outputs" / "extract"
    snapshot.mkdir(parents=True)
    (snapshot / "1.txt").write_text('{"formalName":"Completed"}', encoding="utf-8")
    runtime = {
        str(item): SimpleNamespace(stages={"extract": SimpleNamespace(state="success")}),
    }
    _require_complete_single_extract_stage(
        {"final": {"finished_chunks": 1}}, runtime, [str(item)], expected,
    )
    names = sorted(fp.name for fp in snapshot.glob("*.txt"))
    assert names == ["0.txt", "1.txt"]
    source = [fp.read_text(encoding="utf-8") for fp in sorted(snapshot.glob("*.txt"))]
    result = json.loads(_merge_single_extract_stage_json_parts(source, SimpleNamespace(
        merge_conflict_policy="prefer_left", merge_dedup_lists=False, merge_log_changes=False,
    )))
    assert result == {
        "inputName": "Prior", "formalName": "Completed",
        "keyFunctions": ["old", "new"],
    }


def test_resume_missing_retained_success_fails_before_snapshot_reconstruction(tmp_path):
    item = tmp_path / "row_failed_resume"
    (item / "TODO").mkdir(parents=True)
    _stage_success(item, {"0.txt": '{"inputName":"prior"}'})
    (item / "TODO" / "0.txt").write_text("prompt:0.txt", encoding="utf-8")
    (item / "TODO" / "1.txt").write_text("prompt:1.txt", encoding="utf-8")
    expected = _expected_single_extract_slice_files([str(item)])
    (item / "Success" / "0.txt").unlink()
    _stage_success(item, {"1.txt": '{"formalName":"new"}'})
    runtime = {
        str(item): SimpleNamespace(stages={"extract": SimpleNamespace(state="success")}),
    }
    with pytest.raises(RuntimeError, match="Success slice coverage"):
        _require_complete_single_extract_stage(
            {"final": {"finished_chunks": 1}}, runtime, [str(item)], expected,
        )
    assert not (item / "_stage_outputs" / "extract").exists()


def test_expected_full_set_includes_running_slices_before_resume_recovery(tmp_path):
    item = tmp_path / "row_running"
    (item / "TODO").mkdir(parents=True)
    (item / "RUNNING").mkdir(parents=True)
    (item / "Success").mkdir(parents=True)
    (item / "Success" / "0.txt").write_text("completed", encoding="utf-8")
    (item / "RUNNING" / "1.txt").write_text("interrupted", encoding="utf-8")
    (item / "TODO" / "2.txt").write_text("pending", encoding="utf-8")
    expected = _expected_single_extract_slice_files([str(item)])
    assert tuple(expected[str(item)]) == ("1.txt", "2.txt")
    (item / "TODO" / "0.txt").write_text("current source includes completed member", encoding="utf-8")
    assert tuple(_expected_single_extract_slice_files([str(item)])[str(item)]) == (
        "0.txt", "1.txt", "2.txt"
    )


def test_retokenized_shorter_source_ignores_orphan_success_from_older_layout(tmp_path):
    item = tmp_path / "row_shortened"
    todo = item / "TODO"
    todo.mkdir(parents=True)
    for name in ("0.txt", "1.txt"):
        (todo / name).write_text("prompt:" + name, encoding="utf-8")
    _stage_success(item, {
        "0.txt": '{"current":["A"]}',
        "1.txt": '{"current":["B"]}',
        "2.txt": '{"stale":["must-not-write-back"]}',
    })
    expected = _expected_single_extract_slice_files([str(item)])
    assert tuple(expected[str(item)]) == ("0.txt", "1.txt")

    # Resume prunes current completed TODO but leaves historical Success 2.txt.
    for fp in todo.glob("*.txt"):
        fp.unlink()
    runtime = {
        str(item): SimpleNamespace(stages={"extract": SimpleNamespace(state="success")}),
    }
    _require_complete_single_extract_stage(
        {"final": {"finished_chunks": 1}}, runtime, [str(item)], expected,
    )
    snapshot = item / "_stage_outputs" / "extract"
    actual = sorted(snapshot.glob("*.txt"))
    assert [fp.name for fp in actual] == ["0.txt", "1.txt"]
    merged = _merge_single_extract_stage_json_parts(
        [fp.read_text(encoding="utf-8") for fp in actual],
        SimpleNamespace(merge_conflict_policy="prefer_left", merge_log_changes=False),
    )
    assert json.loads(merged) == {"current": ["A", "B"]}
    assert "stale" not in merged
    assert (item / "Success" / "2.txt").exists()  # Do not destructively prune history.


def test_orphan_success_alone_cannot_establish_current_slice_layout(tmp_path):
    item = tmp_path / "row_no_current_source"
    (item / "TODO").mkdir(parents=True)
    _stage_success(item, {"0.txt": '{"previous":true}'})
    expected = _expected_single_extract_slice_files([str(item)])
    assert expected[str(item)] == {}
    runtime = {
        str(item): SimpleNamespace(stages={"extract": SimpleNamespace(state="success")}),
    }
    with pytest.raises(RuntimeError, match="missing expected current input slices"):
        _require_complete_single_extract_stage(
            {"final": {"finished_chunks": 1}}, runtime, [str(item)], expected,
        )
    assert not (item / "_stage_outputs" / "extract").exists()


def test_resume_same_name_old_result_with_wrong_prompt_never_reused(tmp_path):
    from czjLLM.prompt_pipeline.pipeline_controller import _drop_resumed_todo_by_success

    item = tmp_path / "row_same_name"
    todo = item / "TODO"
    todo.mkdir(parents=True)
    (todo / "0.txt").write_text("new source content", encoding="utf-8")
    _stage_success(item, {"0.txt": '{"from_old_input":true}'})
    # Even if Success has a newer timestamp, its stored prompt digest is old.
    import os
    os.utime(item / "Success" / "0.txt", None)
    assert not valid_success(str(item), "0.txt", digest_text("new source content"))
    assert _drop_resumed_todo_by_success(
        str(item), require_prompt_identity=True,
    ) == 0
    assert (todo / "0.txt").exists()
    runtime = {str(item): SimpleNamespace(stages={"extract": SimpleNamespace(state="success")})}
    with pytest.raises(RuntimeError, match="Success slice coverage"):
        _require_complete_single_extract_stage(
            {"final": {"finished_chunks": 1}}, runtime, [str(item)],
            _expected_single_extract_slice_files([str(item)]),
        )


def test_resume_same_prompt_and_matching_output_provenance_can_reuse(tmp_path):
    from czjLLM.prompt_pipeline.pipeline_controller import _drop_resumed_todo_by_success

    item = tmp_path / "row_matched"
    todo = item / "TODO"
    todo.mkdir(parents=True)
    (todo / "0.txt").write_text("prompt:0.txt", encoding="utf-8")
    _stage_success(item, {"0.txt": '{"valid":true}'})
    expected = _expected_single_extract_slice_files([str(item)])
    assert _drop_resumed_todo_by_success(
        str(item), require_prompt_identity=True,
    ) == 1
    assert not (todo / "0.txt").exists()
    runtime = {str(item): SimpleNamespace(stages={"extract": SimpleNamespace(state="success")})}
    _require_complete_single_extract_stage(
        {"final": {"finished_chunks": 1}}, runtime, [str(item)], expected,
    )


def test_success_output_tampering_invalidates_prompt_identity(tmp_path):
    item = tmp_path / "row_tampered"
    _stage_success(item, {"0.txt": '{"valid":true}'})
    assert valid_success(str(item), "0.txt", digest_text("prompt:0.txt"))
    (item / "Success" / "0.txt").write_text('{"tampered":true}', encoding="utf-8")
    assert not valid_success(str(item), "0.txt", digest_text("prompt:0.txt"))


def test_retry_split_children_replace_failed_parent_and_preserve_order(tmp_path):
    item = tmp_path / "row_split"
    (item / "TODO").mkdir(parents=True)
    (item / "TODO" / "0.txt").write_text("original prompt", encoding="utf-8")
    expected = _expected_single_extract_slice_files([str(item)])
    record_split_identity(
        str(item / "RUNNING" / "0.txt"), "original prompt",
        [("0-0.txt", "prompt:0-0.txt"), ("0-1.txt", "prompt:0-1.txt")],
    )
    _stage_success(item, {
        "0-0.txt": '{"parts":["first"]}',
        "0-1.txt": '{"parts":["second"]}',
    })
    runtime = {str(item): SimpleNamespace(stages={"extract": SimpleNamespace(state="success")})}
    _require_complete_single_extract_stage(
        {"final": {"finished_chunks": 1}}, runtime, [str(item)], expected,
    )
    snapshot = sorted((item / "_stage_outputs" / "extract").glob("*.txt"))
    assert [p.name for p in snapshot] == ["0-0.txt", "0-1.txt"]
    merged = _merge_single_extract_stage_json_parts(
        [p.read_text(encoding="utf-8") for p in snapshot],
        SimpleNamespace(merge_log_changes=False, merge_dedup_lists=False),
    )
    assert json.loads(merged) == {"parts": ["first", "second"]}


def test_missing_split_child_must_fail_closed(tmp_path):
    item = tmp_path / "row_missing_child"
    (item / "TODO").mkdir(parents=True)
    (item / "TODO" / "0.txt").write_text("original prompt", encoding="utf-8")
    record_split_identity(
        str(item / "RUNNING" / "0.txt"), "original prompt",
        [("0-0.txt", "prompt:0-0.txt"), ("0-1.txt", "prompt:0-1.txt")],
    )
    _stage_success(item, {"0-0.txt": '{"parts":["first"]}'})
    runtime = {str(item): SimpleNamespace(stages={"extract": SimpleNamespace(state="success")})}
    with pytest.raises(RuntimeError, match="Success slice coverage"):
        _require_complete_single_extract_stage(
            {"final": {"finished_chunks": 1}}, runtime, [str(item)],
            _expected_single_extract_slice_files([str(item)]),
        )
    assert not (item / "_stage_outputs" / "extract").exists()


def test_split_lineage_from_old_parent_prompt_is_not_current(tmp_path):
    item = tmp_path / "row_old_split"
    (item / "TODO").mkdir(parents=True)
    (item / "TODO" / "0.txt").write_text("new input prompt", encoding="utf-8")
    record_split_identity(
        str(item / "RUNNING" / "0.txt"), "old input prompt",
        [("0-0.txt", "prompt:0-0.txt"), ("0-1.txt", "prompt:0-1.txt")],
    )
    _stage_success(item, {
        "0-0.txt": '{"parts":["old first"]}',
        "0-1.txt": '{"parts":["old second"]}',
    })
    with pytest.raises(ValueError, match="missing or stale"):
        resolve_success_leaves(str(item), "0.txt", digest_text("new input prompt"))


def _interrupted_split_setup(tmp_path):
    item = tmp_path / "row_crash"
    running = item / "RUNNING"
    running.mkdir(parents=True)
    parent = running / "0.txt"
    parent.write_text("original prompt", encoding="utf-8")
    children = [("0-0.txt", "first half prompt"), ("0-1.txt", "second half prompt")]
    return item, parent, children


def test_split_intent_precedes_partial_child_install_and_recovers(tmp_path, monkeypatch):
    import czjLLM.prompt_pipeline.slice_identity as identity

    item, parent, children = _interrupted_split_setup(tmp_path)
    real = identity._write_child_prompt
    calls = []

    def stop_after_first(path, text):
        calls.append(path.name)
        if len(calls) == 2:
            raise RuntimeError("simulated process loss before second child")
        real(path, text)

    monkeypatch.setattr(identity, "_write_child_prompt", stop_after_first)
    with pytest.raises(RuntimeError, match="simulated process loss"):
        install_split_prompts(str(parent), "original prompt", children)
    assert parent.exists()
    assert (item / "TODO" / "0-0.txt").is_file()
    assert not (item / "TODO" / "0-1.txt").exists()
    assert (item / "_extract_slice_identity" / "splits" / "0.txt.json").exists()
    reconcile_split_transitions(str(item))
    assert parent.is_file()
    assert not (item / "TODO" / "0-0.txt").exists()
    assert not (item / "_extract_slice_identity" / "splits" / "0.txt.json").exists()
    assert tuple(_expected_single_extract_slice_files([str(item)])[str(item)]) == ("0.txt",)


def test_split_parent_and_both_children_before_unlink_recover_without_double_roots(tmp_path):
    item, parent, children = _interrupted_split_setup(tmp_path)
    install_split_prompts(str(parent), "original prompt", children)
    assert parent.is_file()  # simulated crash immediately before parent unlink
    assert sorted(p.name for p in (item / "TODO").glob("*.txt")) == [
        "0-0.txt", "0-1.txt",
    ]
    reconcile_split_transitions(str(item))
    assert parent.is_file()
    assert list((item / "TODO").glob("*.txt")) == []
    assert tuple(_expected_single_extract_slice_files([str(item)])[str(item)]) == ("0.txt",)


def test_committed_split_after_parent_unlink_keeps_both_children(tmp_path):
    item, parent, children = _interrupted_split_setup(tmp_path)
    install_split_prompts(str(parent), "original prompt", children)
    parent.unlink()
    reconcile_split_transitions(str(item))
    expected = _expected_single_extract_slice_files([str(item)])[str(item)]
    assert tuple(expected) == ("0-0.txt", "0-1.txt")
    assert expected["0-0.txt"] == digest_text("first half prompt")
    assert expected["0-1.txt"] == digest_text("second half prompt")


def test_incomplete_committed_split_without_parent_fails_closed(tmp_path):
    item, parent, children = _interrupted_split_setup(tmp_path)
    install_split_prompts(str(parent), "original prompt", children)
    parent.unlink()
    (item / "TODO" / "0-1.txt").unlink()
    with pytest.raises(RuntimeError, match="without recoverable parent"):
        reconcile_split_transitions(str(item))


def test_split_reconciliation_refuses_to_delete_unrelated_changed_child(tmp_path):
    item, parent, children = _interrupted_split_setup(tmp_path)
    install_split_prompts(str(parent), "original prompt", children)
    child = item / "TODO" / "0-0.txt"
    child.write_text("unrelated newer prompt", encoding="utf-8")
    with pytest.raises(RuntimeError, match="changed extract split child"):
        reconcile_split_transitions(str(item))
    assert parent.is_file()
    assert child.read_text(encoding="utf-8") == "unrelated newer prompt"


def test_split_reconciliation_retries_parent_after_crash_without_persisting_prompts(tmp_path):
    item, parent, children = _interrupted_split_setup(tmp_path)
    install_split_prompts(str(parent), "original prompt", children)
    reconcile_split_transitions(str(item))
    record_dir = item / "_extract_slice_identity"
    assert all(
        "original prompt" not in p.read_text(encoding="utf-8")
        and "first half prompt" not in p.read_text(encoding="utf-8")
        for p in record_dir.rglob("*.json")
    )
    assert parent.is_file()
