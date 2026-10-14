"""Issue #211: offline SQL/Excel integration through real scheduler and sinks.

Only the OpenAI-compatible HTTP boundary and deterministic *tokenizer cut
points* are simulated. Input files, production orchestrator, prompt queue,
stage merge/manifest, SQLite and Excel writes/readback are real. The mocked
tokenizer changes segmentation, not LLM dispatch, merge or persistence.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from czjLLM.handlers import handle_data_mode as data_handler
from czjLLM.job_manager.job_config import LLMJobConfig
from czjLLM.prompt_pipeline.dispatch_parallelism import attach_execution_budget
from czjLLM.prompt_pipeline import prompt_generator
from czjLLM.sql_mode.entry import steps as sql_steps


pytestmark = pytest.mark.e2e

_SOURCE = "E2E_JSON_SPLIT_INPUT should be processed in two different segments"

# Real callable-task dependencies used for persisted-stage fingerprint tests.
_E2E_GLOBAL_PROMPT_RULE = "E2E_JSON_EFFECTIVE_TASK"
_E2E_GLOBAL_FLAG = False


def _e2e_global_helper(content):
    return content


def _e2e_global_template(content):
    return (_E2E_GLOBAL_PROMPT_RULE + "\n"
            + (_e2e_global_helper(content) if _E2E_GLOBAL_FLAG else content))


def _force_two_source_slices(monkeypatch):
    """Fix just the input split boundary so this acceptance always has 2 slices.

    The real prompt generator and all later production stages still execute.
    """
    original = prompt_generator.TokenizerWrapper.tokenize

    def deterministic(self, text, *args, **kwargs):
        if str(text).startswith("E2E_JSON_SPLIT_INPUT"):
            return {"ctxCut": ["E2E_JSON_PART_A", "E2E_JSON_PART_B"]}
        return original(self, text, *args, **kwargs)

    monkeypatch.setattr(prompt_generator.TokenizerWrapper, "tokenize", deterministic)


def _ctx(fake_openai, tmp_path, backend):
    ctx = LLMJobConfig()
    ctx.mode = backend
    ctx.task = "E2E_JSON_RESPONSE"
    ctx.model_spec = fake_openai.model_spec
    ctx.model_spec_name = "e2e-model"
    ctx.max_tokens = 128
    ctx.PGMSubDir = str(tmp_path)
    ctx.prompt_dir = str(tmp_path / "prompts")
    ctx.llm_source_dir = str(tmp_path / "work")
    ctx.llm_source_finished_dir = str(tmp_path / "finished")
    ctx.log_dir = str(tmp_path / "logs")
    ctx.n_process = 1
    ctx.slice_parallelism = 2
    ctx.schedule_todo_wait_seconds = 5
    ctx.pending_running_all_deferred_wait_seconds = 0
    ctx.reduction = {"enabled": False, "profile": "concat_text"}
    ctx.merge_slices = True
    ctx.sql_enable_multistage_stream = True
    # The real worker must consume TODO after a verified Success; retaining
    # processed prompts makes stage runtime correctly report work outstanding.
    ctx.removeFinPromptFile = True
    ctx.resume_policy = "resume"
    ctx.stages = [
        {
            "name": "extract",
            "task": "E2E_JSON_RESPONSE",
            "input_from": "original",
            "persist_output": "final",
            "input_col": "body" if backend == "sql" else "File",
        },
    ]
    ctx.sql_writeback_rules = [
        {"output_col": "analysis", "source": "stage", "stage": "extract"},
    ]
    for location in (ctx.prompt_dir, ctx.llm_source_dir, ctx.llm_source_finished_dir, ctx.log_dir):
        Path(location).mkdir(parents=True, exist_ok=True)
    attach_execution_budget(ctx)
    return ctx


@pytest.mark.parametrize("backend", ["sql", "table"], ids=["sqlite", "excel"])
@pytest.mark.parametrize("task_key_variant", [False, True], ids=["same-task", "task-key-override"])
def test_two_json_slices_write_one_valid_persisted_result(
    backend, task_key_variant, fake_openai, tmp_path, monkeypatch,
):
    _force_two_source_slices(monkeypatch)
    # Avoid the interactive 10-second first-row pause, without bypassing the
    # actual TXT prompt generator, scheduler, model transport or row merger.
    from czjLLM.sql_mode.runtime import scheduler

    original_handle = scheduler.handle_single_input_file

    def no_pause(*args, **kwargs):
        kwargs["pause_seconds"] = 0
        return original_handle(*args, **kwargs)

    monkeypatch.setattr(scheduler, "handle_single_input_file", no_pause)

    ctx = _ctx(fake_openai, tmp_path, backend)
    if task_key_variant:
        # Initial slice generation sees the fallback task, while runtime
        # resolves task_key to a different effective task. The stage must
        # re-render EACH raw slice without collapsing it to one full row.
        ctx.stages[0]["task_key"] = "E2E_JSON_EFFECTIVE"
        ctx.taskSetting = {"E2E_JSON_EFFECTIVE": "E2E_JSON_EFFECTIVE_TASK"}
    params = {
        "input_col": "body" if backend == "sql" else "File",
        "output_col": "analysis",
        "record_update_time": False,
        "flatten_json_output": False,
        "sql_writeback_rules": ctx.sql_writeback_rules,
        "sql_flatten_writeback_rules": [
            {"writeback_rule": 0, "enabled": False},
        ],
    }
    if backend == "sql":
        db = tmp_path / "rows.sqlite"
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE source (id TEXT PRIMARY KEY, body TEXT)")
            conn.execute("CREATE TABLE results (id TEXT PRIMARY KEY, analysis TEXT)")
            conn.execute("INSERT INTO source VALUES (?, ?)", ("row211", _SOURCE))
        cfg = {
            "server": str(db), "table_name": "source", "target_table": "results",
            "primary_key": "id", "input_col": "body", "output_col": "analysis",
            "reset_output": False,
        }
        monkeypatch.setattr(sql_steps, "load_sql_cfg", lambda *_args: cfg)
    else:
        source = tmp_path / "source.xlsx"
        dest = tmp_path / "result.xlsx"
        pd.DataFrame({"id": ["row211"], "File": [_SOURCE]}).to_excel(source, index=False)
        params.update({
            "input_excel_file": str(source), "output_excel_file": str(dest),
            "primary_key": "id",
        })

    data_handler.handle_data_mode(
        ctx, lambda key, default=None: params.get(key, default),
        SimpleNamespace(config="offline-e2e"),
    )

    requests = ["\\n".join(str(m.get("content", "")) for m in request["body"].get("messages", []))
                for request in fake_openai.requests]
    assert any("E2E_JSON_PART_A" in prompt and "E2E_JSON_PART_B" not in prompt
               for prompt in requests), requests
    assert any("E2E_JSON_PART_B" in prompt and "E2E_JSON_PART_A" not in prompt
               for prompt in requests), requests

    if task_key_variant:
        assert all("E2E_JSON_EFFECTIVE_TASK" in prompt for prompt in requests)
        assert all("E2E_JSON_RESPONSE" not in prompt for prompt in requests)

    if backend == "sql":
        with sqlite3.connect(db) as conn:
            persisted = conn.execute(
                "SELECT analysis FROM results WHERE id = ?", ("row211",)
            ).fetchone()
        assert persisted is not None
        output = persisted[0]
    else:
        result = pd.read_excel(dest, sheet_name="LLM_result")
        assert len(result) == 1
        output = result.loc[0, "analysis"]

    assert isinstance(output, str)
    assert json.loads(output) == {"keyFunctions": ["first", "second"]}
    assert ctx._execution_budget.snapshot().in_use == 0


@pytest.mark.parametrize("backend", ["sql", "table"], ids=["sqlite-resume", "excel-resume"])
def test_interrupted_split_resumes_only_missing_sibling_and_persists_both(
    backend, fake_openai, tmp_path,
):
    """Restart a real extract workspace with Success A + queued B.

    Calls real localhost LLM client and the actual single-extract controller,
    then the production writeback selector and physical sink for each backend.
    This is a resume integration, distinct from the scheduler acceptance above.
    """
    from czjLLM.prompt_pipeline.pipeline_controller import (
        PromptAPIPipeline, process_prompt_and_merge_multistage,
    )
    from czjLLM.prompt_pipeline.slice_identity import (
        install_split_prompts, record_success_identity,
    )
    from czjLLM.sql_mode.runtime.row_merger_generic import _build_writeback_values
    from czjLLM.sql_mode.runtime.sinks.excel_sink import ExcelSink
    from czjLLM.sql_mode.runtime.sinks.sql_sink import SqlSink

    ctx = _ctx(fake_openai, tmp_path, backend)
    ctx.input_col = "body" if backend == "sql" else "File"
    ctx.output_col = "analysis"
    ctx.primary_key = "id"
    ctx.record_update_time = False
    ctx.flatten_json_output = False
    ctx.sql_flatten_writeback_rules = [{"writeback_rule": 0, "enabled": False}]
    ctx.stage_source_inputs = {ctx.input_col: _SOURCE}
    ctx.main_file_name = "resume211"
    ctx.temp_txt_finished_dir = str(tmp_path / "finished")
    source = tmp_path / "resume211.txt"
    source.write_text(_SOURCE, encoding="utf-8")
    item = Path(ctx.prompt_dir) / "resume211"
    running = item / "RUNNING"
    running.mkdir(parents=True)
    parent = running / "0.txt"
    parent.write_text("E2E_JSON_RESPONSE " + _SOURCE, encoding="utf-8")
    children = [("0-0.txt", "E2E_JSON_PART_A"), ("0-1.txt", "E2E_JSON_PART_B")]
    install_split_prompts(str(parent), parent.read_text(encoding="utf-8"), children)
    parent.unlink()

    # First run was interrupted only *after* A reached authoritative Success.
    complete_prompt = item / "TODO" / "0-0.txt"
    success = item / "Success" / complete_prompt.name
    success.parent.mkdir()
    first = PromptAPIPipeline(
        task="E2E_JSON_RESPONSE", content=complete_prompt.read_text(),
        OutputSaveFN=str(success),
        model_spec=fake_openai.model_spec,
        PGMSubDir=str(tmp_path),
    ).proc()
    assert first["ok"], first
    record_success_identity(
        str(complete_prompt), str(success),
        complete_prompt.read_text(encoding="utf-8"), first["output"],
    )
    complete_prompt.unlink()

    before_restart = len(fake_openai.requests)
    combined = process_prompt_and_merge_multistage(ctx, str(source))
    assert Path(combined).is_file()
    later = fake_openai.requests[before_restart:]
    assert later, "resumed execution must call the provider for B"
    assert all(
        "E2E_JSON_PART_A" not in str(request["body"])
        for request in later
    ), "already successful sibling A must never be sent again"
    assert any("E2E_JSON_PART_B" in str(request["body"]) for request in later)

    # Resolve the real stage manifest/writeback selector (not a fixture JSON
    # concatenation), then persist to a physical SQLite or Excel destination.
    write_map, _flatten_source, _source_logs, write_sources = _build_writeback_values(
        ctx, str(combined), Path(combined).read_text(encoding="utf-8"),
    )
    assert write_sources["analysis"] == "stage:extract"
    assert json.loads(write_map["analysis"]) == {"keyFunctions": ["first", "second"]}

    if backend == "sql":
        path = tmp_path / "resume.sqlite"
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE source (id TEXT PRIMARY KEY, body TEXT)")
            connection.execute("CREATE TABLE results (id TEXT PRIMARY KEY, analysis TEXT)")
            connection.execute("INSERT INTO source VALUES (?, ?)", ("row211", _SOURCE))
        ctx.sqlite_path = str(path)
        ctx.is_sqlite = True
        ctx.sql_table = "source"
        ctx.target_table = "results"
        sink = SqlSink(ctx, is_sqlite=True)
        sink.open()
        try:
            sink.write_main("row211", write_map["analysis"])
        finally:
            sink.close()
        with sqlite3.connect(path) as connection:
            row = connection.execute(
                "SELECT analysis FROM results WHERE id = ?", ("row211",)
            ).fetchone()
        output = row[0] if row else None
    else:
        source_xlsx = tmp_path / "resume_source.xlsx"
        target_xlsx = tmp_path / "resume_output.xlsx"
        pd.DataFrame({"id": ["row211"], "File": [_SOURCE]}).to_excel(
            source_xlsx, index=False,
        )
        sink = ExcelSink(
            ctx, input_path=str(source_xlsx), output_path=str(target_xlsx),
            main_sheet="LLM_result", flush_main_every=1,
        )
        sink.open()
        try:
            sink.write_main("row211", write_map["analysis"])
        finally:
            sink.close()
        output = pd.read_excel(target_xlsx, sheet_name="LLM_result").loc[0, "analysis"]

    assert json.loads(output) == {"keyFunctions": ["first", "second"]}


@pytest.mark.parametrize("backend", ["sql", "table"], ids=["sqlite", "excel"])
@pytest.mark.parametrize("resume_policy", ["resume", "smart_reset"])
@pytest.mark.parametrize("resume_case", ["accept", "accept-global", "accept-context", "reject-stale-source", "reject-drifted-prompt", "reject-drifted-global", "reject-drifted-helper"])
def test_task_key_override_recovers_completed_original_slice(
    backend, resume_policy, resume_case, fake_openai, tmp_path, monkeypatch,
):
    """Crash after the original A/B manifest was committed, finish only B.

    This exercises the actual extract controller, persisted raw/dispatch
    provenance, real localhost HTTP calls, and the respective physical sink.
    A is already committed in Success, not in TODO when the second run starts.
    """
    from czjLLM.prompt_pipeline import pipeline_controller as controller
    from czjLLM.prompt_pipeline.pipeline_controller import PromptAPIPipeline
    from czjLLM.prompt_pipeline.slice_identity import record_success_identity
    from czjLLM.sql_mode.runtime.row_merger_generic import _build_writeback_values
    from czjLLM.sql_mode.runtime.sinks.excel_sink import ExcelSink
    from czjLLM.sql_mode.runtime.sinks.sql_sink import SqlSink

    _force_two_source_slices(monkeypatch)
    ctx = _ctx(fake_openai, tmp_path, backend)
    ctx.resume_policy = resume_policy
    ctx.input_col = "body" if backend == "sql" else "File"
    ctx.output_col = "analysis"
    ctx.primary_key = "id"
    ctx.record_update_time = False
    ctx.flatten_json_output = False
    ctx.stage_source_inputs = {}  # Original-input route, not source-input override
    ctx.sql_flatten_writeback_rules = [{"writeback_rule": 0, "enabled": False}]
    ctx.stages[0]["task_key"] = "E2E_JSON_EFFECTIVE"
    ctx.taskSetting = {"E2E_JSON_EFFECTIVE": "E2E_JSON_EFFECTIVE_TASK"}
    if resume_case in {"accept-global", "reject-drifted-global", "reject-drifted-helper"}:
        ctx.taskSetting["E2E_JSON_EFFECTIVE"] = {
            "CT_name": "E2E callable global dependency",
            "template": _e2e_global_template,
        }
    ctx.main_file_name = "rawresume211"
    ctx.temp_txt_finished_dir = str(tmp_path / "finished")

    source = tmp_path / "rawresume211.txt"
    source.write_text(_SOURCE, encoding="utf-8")
    item = Path(ctx.prompt_dir) / source.stem
    todo = item / "TODO"
    todo.mkdir(parents=True)
    for i, part in enumerate(("E2E_JSON_PART_A", "E2E_JSON_PART_B")):
        (todo / f"{i}.txt").write_text(
            f"E2E_JSON_RESPONSE\n\n{part}", encoding="utf-8",
        )

    # Simulate a process interruption at the LLM boundary, AFTER the real
    # pipeline prepared effective-task prompts and committed raw provenance.
    def crash_before_dispatch(*_args, **_kwargs):
        raise RuntimeError("injected-after-stage-preparation")

    with monkeypatch.context() as interrupted:
        interrupted.setattr(controller, "_call_llm_with_task_override", crash_before_dispatch)
        with pytest.raises(RuntimeError, match="injected-after-stage-preparation"):
            controller.process_prompt_and_merge_multistage(ctx, str(source))

    saved = item / "_extract_slice_identity" / "source" / "original.json"
    evidence = json.loads(saved.read_text(encoding="utf-8"))
    assert evidence["names"] == ["0.txt", "1.txt"]
    assert set(evidence["dispatch_sha256"]) == {"0.txt", "1.txt"}

    first_prompt = todo / "0.txt"
    assert "E2E_JSON_EFFECTIVE_TASK" in first_prompt.read_text(encoding="utf-8")
    first_output = item / "Success" / first_prompt.name
    first_output.parent.mkdir(exist_ok=True)
    first = PromptAPIPipeline(
        task="E2E_JSON_EFFECTIVE_TASK", content=first_prompt.read_text(encoding="utf-8"),
        OutputSaveFN=str(first_output), model_spec=fake_openai.model_spec,
        PGMSubDir=str(tmp_path),
    ).proc()
    assert first["ok"], first
    record_success_identity(
        str(first_prompt), str(first_output),
        first_prompt.read_text(encoding="utf-8"), first["output"],
    )
    first_prompt.unlink()

    if resume_policy == "smart_reset":
        assert saved.is_file()
        assert len(list((item / "_stage_outputs" / "original").glob("*.txt"))) == 2

    if resume_case == "reject-stale-source":
        # Same tokenizer chunks but different source SHA: no stale success reuse.
        source.write_text(_SOURCE + " CHANGED", encoding="utf-8")
        before_resume = len(fake_openai.requests)
        with pytest.raises(RuntimeError, match="source-slice provenance"):
            controller.process_prompt_and_merge_multistage(ctx, str(source))
        assert len(fake_openai.requests) == before_resume
        return

    if resume_case == "reject-drifted-prompt":
        # A has already succeeded and the saved dispatch fingerprint binds
        # B as well. Inject a deterministic renderer drift after stage
        # preparation; no B request or provenance overwrite is permissible.
        old_evidence = saved.read_bytes()
        calls_before = len(fake_openai.requests)
        original_render = controller._build_stage_prompt_text

        def drifted_renderer(task, raw, runtime_ctx):
            rendered = original_render(task, raw, runtime_ctx)
            return rendered + "\\nCORRUPTED" if raw == "E2E_JSON_PART_B" else rendered

        with monkeypatch.context() as patch:
            patch.setattr(controller, "_build_stage_prompt_text", drifted_renderer)
            with pytest.raises(RuntimeError, match="extract dispatch prompt changed"):
                controller.process_prompt_and_merge_multistage(ctx, str(source))
        assert saved.read_bytes() == old_evidence
        assert len(fake_openai.requests) == calls_before
        assert first_output.is_file()
        return

    if resume_case in {"reject-drifted-global", "reject-drifted-helper"}:
        # A is Success; B is TODO. Refuse changed semantics before any LLM
        # dispatch or durable provenance overwrite.
        with monkeypatch.context() as drift:
            if resume_case == "reject-drifted-global":
                drift.setattr(sys.modules[__name__], "_E2E_GLOBAL_PROMPT_RULE",
                              "E2E_JSON_EFFECTIVE_TASK CHANGED")
            else:
                drift.setattr(sys.modules[__name__], "_e2e_global_helper",
                              lambda content: "CHANGED " + content)
            calls_before = len(fake_openai.requests)
            prior = saved.read_bytes()
            with pytest.raises(RuntimeError, match="extract stage task changed"):
                controller.process_prompt_and_merge_multistage(ctx, str(source))
            assert len(fake_openai.requests) == calls_before
            assert saved.read_bytes() == prior
            assert first_output.is_file()
        return

    before_resume = len(fake_openai.requests)
    result_marker = controller.process_prompt_and_merge_multistage(ctx, str(source))
    assert Path(result_marker).is_file()
    assert saved.is_file()
    assert json.loads(saved.read_text(encoding="utf-8"))["names"] == ["0.txt", "1.txt"]
    additional = fake_openai.requests[before_resume:]
    assert additional and all("E2E_JSON_PART_A" not in str(req["body"]) for req in additional)
    assert all("E2E_JSON_EFFECTIVE_TASK" in str(req["body"]) for req in additional)
    assert any("E2E_JSON_PART_B" in str(req["body"]) for req in additional)

    values, _flatten, _source_log, selected = _build_writeback_values(
        ctx, str(result_marker), Path(result_marker).read_text(encoding="utf-8"),
    )
    assert selected["analysis"] == "stage:extract"
    assert json.loads(values["analysis"]) == {"keyFunctions": ["first", "second"]}

    if backend == "sql":
        db = tmp_path / "rawresume.sqlite"
        with sqlite3.connect(db) as con:
            con.execute("CREATE TABLE source (id TEXT PRIMARY KEY, body TEXT)")
            con.execute("CREATE TABLE results (id TEXT PRIMARY KEY, analysis TEXT)")
            con.execute("INSERT INTO source VALUES (?, ?)", ("row211", _SOURCE))
        ctx.sqlite_path = str(db)
        ctx.is_sqlite = True
        ctx.sql_table, ctx.target_table = "source", "results"
        sink = SqlSink(ctx, is_sqlite=True)
        sink.open()
        try:
            sink.write_main("row211", values["analysis"])
        finally:
            sink.close()
        with sqlite3.connect(db) as con:
            written = con.execute("SELECT analysis FROM results WHERE id = ?", ("row211",)).fetchone()[0]
    else:
        workbook = tmp_path / "rawresume_input.xlsx"
        output_book = tmp_path / "rawresume_output.xlsx"
        pd.DataFrame({"id": ["row211"], "File": [_SOURCE]}).to_excel(workbook, index=False)
        sink = ExcelSink(
            ctx, input_path=str(workbook), output_path=str(output_book),
            main_sheet="LLM_result", flush_main_every=1,
        )
        sink.open()
        try:
            sink.write_main("row211", values["analysis"])
        finally:
            sink.close()
        written = pd.read_excel(output_book, sheet_name="LLM_result").loc[0, "analysis"]

    assert json.loads(written) == {"keyFunctions": ["first", "second"]}


    # A+B are now entirely in Success, with zero root TODO. A smart reset
    # must reconstruct the stage output, NOT invoke the model or replace the
    # accepted Success files with nondeterministic new ones.
    assert not list(todo.glob("*.txt"))
    ctx.resume_policy = "smart_reset"
    completed_before = {
        x.name: x.read_bytes() for x in (item / "Success").glob("*.txt")
    }
    calls_before = len(fake_openai.requests)
    reused_marker = controller.process_prompt_and_merge_multistage(ctx, str(source))
    assert Path(reused_marker).is_file()
    assert len(fake_openai.requests) == calls_before
    assert completed_before == {
        x.name: x.read_bytes() for x in (item / "Success").glob("*.txt")
    }
    reused_values, *_ = _build_writeback_values(
        ctx, str(reused_marker), Path(reused_marker).read_text(encoding="utf-8"),
    )
    assert json.loads(reused_values["analysis"]) == {"keyFunctions": ["first", "second"]}

    if resume_case == "accept-global":
        # With every leaf already Success and no TODO, reject stale outputs
        # even though smart_reset otherwise requires ZERO provider calls.
        with monkeypatch.context() as drift:
            drift.setattr(sys.modules[__name__], "_E2E_GLOBAL_FLAG", True)
            calls_before = len(fake_openai.requests)
            with pytest.raises(RuntimeError, match="extract stage task changed"):
                controller.process_prompt_and_merge_multistage(ctx, str(source))
            assert len(fake_openai.requests) == calls_before
            assert completed_before == {
                x.name: x.read_bytes() for x in (item / "Success").glob("*.txt")
            }

    if resume_case == "accept-context":
        # Same effective task, same A/B Success, but renderer options changed.
        # The all-Success fast path must refuse cache reuse without an LLM call.
        for field, replacement in (
            ("keyConsiderations", "ADDED_CONTEXT_FOR_NEW_PROMPT"),
            ("think_mode", not bool(getattr(ctx, "think_mode", True))),
        ):
            with monkeypatch.context() as drift:
                drift.setattr(ctx, field, replacement)
                calls_before = len(fake_openai.requests)
                with pytest.raises(RuntimeError, match="extract stage task changed"):
                    controller.process_prompt_and_merge_multistage(ctx, str(source))
                assert len(fake_openai.requests) == calls_before
                assert completed_before == {
                    x.name: x.read_bytes() for x in (item / "Success").glob("*.txt")
                }

    # A full restart with a modified source must fail BEFORE removing Success.
    ctx.resume_policy = "full_restart"
    source.write_text(_SOURCE + " CHANGED", encoding="utf-8")
    with pytest.raises(RuntimeError, match="original source has changed"):
        controller.process_prompt_and_merge_multistage(ctx, str(source))
    assert completed_before == {
        x.name: x.read_bytes() for x in (item / "Success").glob("*.txt")
    }
    source.write_text(_SOURCE, encoding="utf-8")

    # An explicit full restart may change task_key: it must recompute both
    # source slices using the new effective task and replace old results,
    # rather than rejecting the stale dispatch/task metadata after deletion.
    if resume_policy == "resume":
        ctx.stages[0]["task_key"] = "E2E_RESTART_TASK"
        ctx.taskSetting["E2E_RESTART_TASK"] = "E2E_JSON_NEW_TASK"
        calls_before = len(fake_openai.requests)
        restarted = controller.process_prompt_and_merge_multistage(ctx, str(source))
        assert Path(restarted).is_file()
        fresh = fake_openai.requests[calls_before:]
        assert len(fresh) == 2, fresh
        assert all("E2E_JSON_NEW_TASK" in str(x["body"]) for x in fresh)
        assert any("E2E_JSON_PART_A" in str(x["body"]) for x in fresh)
        assert any("E2E_JSON_PART_B" in str(x["body"]) for x in fresh)
        new_values, *_ = _build_writeback_values(
            ctx, str(restarted), Path(restarted).read_text(encoding="utf-8"),
        )
        assert json.loads(new_values["analysis"]) == {"keyFunctions": ["first", "second"]}



def _callable_task_factory(phrase):
    # Separate function objects (different Python memory addresses) with
    # identical source + captured semantic value have identical identities.
    return lambda content: f"{phrase}\\n\\n{content}"


def test_callable_task_identity_is_stable_across_instances_and_detects_changes():
    from czjLLM.prompt_pipeline.task_fingerprint import fingerprint_task

    first = _callable_task_factory("E2E_JSON_EFFECTIVE_TASK")
    fresh_process_equivalent = _callable_task_factory("E2E_JSON_EFFECTIVE_TASK")
    changed = _callable_task_factory("E2E_OTHER_TASK")
    assert repr(first) != repr(fresh_process_equivalent)
    old_style = str({"task": "E2E_JSON_RESPONSE", "template": first})
    new_style = str({"task": "E2E_JSON_RESPONSE", "template": fresh_process_equivalent})
    assert old_style != new_style
    saved_hash = fingerprint_task({"task": "E2E_JSON_RESPONSE", "template": first})
    assert saved_hash == fingerprint_task({
        "template": fresh_process_equivalent, "task": "E2E_JSON_RESPONSE",
    })
    assert saved_hash != fingerprint_task({
        "task": "E2E_JSON_RESPONSE", "template": changed,
    })
    assert saved_hash != fingerprint_task({
        "task": "DIFFERENT_CONFIG", "template": fresh_process_equivalent,
    })


@pytest.mark.parametrize("policy", ["resume", "smart_reset", "full_restart"])
def test_regular_multistage_input_snapshot_ignores_stale_single_extract_manifest(
    policy, fake_openai, tmp_path, monkeypatch,
):
    from czjLLM.prompt_pipeline import pipeline_controller as controller

    _force_two_source_slices(monkeypatch)
    ctx = _ctx(fake_openai, tmp_path, "table")
    ctx.stages = [
        {"name": "prepare", "task": "E2E_JSON_RESPONSE", "input_from": "original"},
        {"name": "summarize", "task": "E2E_JSON_RESPONSE", "input_from": "original"},
    ]
    ctx.sql_writeback_rules = []  # genuine multistage, not scoped single extract
    ctx.resume_policy = policy
    ctx.main_file_name = "ordinary-stage"
    source = tmp_path / "ordinary-stage.txt"
    source.write_text(_SOURCE, encoding="utf-8")
    item = Path(ctx.prompt_dir) / source.stem
    todo = item / "TODO"
    todo.mkdir(parents=True)
    for i, part in enumerate(("E2E_JSON_PART_A", "E2E_JSON_PART_B")):
        (todo / f"{i}.txt").write_text(
            f"E2E_JSON_RESPONSE\\n\\n{part}", encoding="utf-8",
        )

    snapshot = item / "_stage_outputs" / "original"
    snapshot.mkdir(parents=True)
    (snapshot / "0.txt").write_text("STALE OLD SOURCE", encoding="utf-8")
    stale = item / "_extract_slice_identity" / "source" / "original.json"
    stale.parent.mkdir(parents=True)
    stale.write_text(json.dumps({
        "version": 1, "source_sha256": "0" * 64,
        "names": ["0.txt", "1.txt"], "part_sha256": ["0" * 64, "0" * 64],
    }), encoding="utf-8")

    def stop_after_preparation(*_args, **_kwargs):
        raise RuntimeError("captured-new-stage-preparation")

    with monkeypatch.context() as active:
        active.setattr(controller, "_call_llm_with_task_override", stop_after_preparation)
        with pytest.raises(RuntimeError, match="captured-new-stage-preparation"):
            controller.process_prompt_and_merge_multistage(ctx, str(source))

    assert (snapshot / "0.txt").read_text(encoding="utf-8") == "E2E_JSON_PART_A"
    assert (snapshot / "1.txt").read_text(encoding="utf-8") == "E2E_JSON_PART_B"
    assert json.loads(stale.read_text())["source_sha256"] == "0" * 64


def test_same_line_lambda_templates_bind_bytecode_constants_to_task_identity():
    from czjLLM.prompt_pipeline.task_fingerprint import fingerprint_task

    # inspect.getsource() returns the same *assignment line* for both
    # lambdas, and their module and qualname are likewise identical.
    left, right = (lambda content: "LEFT " + content), (lambda content: "RIGHT " + content)
    assert left.__qualname__ == right.__qualname__
    assert left.__code__.co_code == right.__code__.co_code
    assert left.__code__.co_consts != right.__code__.co_consts
    assert fingerprint_task({"template": left}) != fingerprint_task({"template": right})


def test_task_fingerprint_tracks_globals_flags_and_transitive_helpers():
    from czjLLM.prompt_pipeline.task_fingerprint import fingerprint_task

    source = """
RULE = 'first'
FLAG = False
def helper(text):
    return 'A' + text
def template(content):
    return RULE + (helper(content) if FLAG else content)
"""
    namespace = {"__name__": "e2e_semantics"}
    exec(source, namespace)
    task = {"template": namespace["template"]}
    first = fingerprint_task(task)
    namespace["RULE"] = "second"
    second = fingerprint_task(task)
    namespace["FLAG"] = True
    third = fingerprint_task(task)
    exec("def helper(text): return 'B' + text", namespace)
    fourth = fingerprint_task(task)
    assert len({first, second, third, fourth}) == 4

    same = {"__name__": "e2e_semantics"}
    exec(source, same)
    same["RULE"] = "second"
    same["FLAG"] = True
    exec("def helper(text): return 'B' + text", same)
    assert fourth == fingerprint_task({"template": same["template"]})


def test_task_fingerprint_nested_global_and_cycle_and_fail_closed():
    from czjLLM.prompt_pipeline.task_fingerprint import fingerprint_task

    scope = {"__name__": "e2e_semantics"}
    exec("""
WORD = 'first'
def template(content):
    return ''.join([WORD for _ in range(2)]) + content
""", scope)
    before = fingerprint_task(scope["template"])
    scope["WORD"] = "second"
    assert fingerprint_task(scope["template"]) != before

    exec("""
def first(x):
    return second(x - 1) if x > 0 else 0
def second(x):
    return first(x - 1) if x > 0 else 0
""", scope)
    assert len(fingerprint_task(scope["first"])) == 64

    exec("DYNAMIC = object()\ndef unsafe(content): return str(DYNAMIC) + content", scope)
    with pytest.raises(ValueError, match="unsupported task identity type"):
        fingerprint_task({"template": scope["unsafe"]})


def test_task_fingerprint_is_stable_in_separate_python_processes():
    import subprocess
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    script = """
from czjLLM.prompt_pipeline.task_fingerprint import fingerprint_task
RULE = 'same'
FLAG = True
def helper(content):
    return content.upper()
def template(content):
    return RULE + (helper(content) if FLAG else content)
print(fingerprint_task({'template': template}))
"""
    hashes = [
        subprocess.check_output([sys.executable, "-c", script], cwd=project_root,
                                text=True).strip()
        for _ in range(2)
    ]
    assert hashes[0] == hashes[1]
    assert len(hashes[0]) == 64


def test_callable_keyword_abi_changes_identity_even_with_same_line_lambdas():
    from czjLLM.prompt_pipeline.task_fingerprint import fingerprint_task

    # The renderer calls template(content=...). Identical bytecode with a
    # different parameter name is not interchangeable at that call site.
    first, second = (lambda content: content), (lambda text: text)
    assert first.__code__.co_code == second.__code__.co_code
    assert first.__code__.co_varnames != second.__code__.co_varnames
    assert fingerprint_task({"template": first}) != fingerprint_task({"template": second})


@pytest.mark.parametrize("body", [
    'return globals()["RULE"] + content',
    'return eval("RULE") + content',
    'return locals()["content"] + content',
])
def test_dynamic_namespace_task_lookup_fails_closed(body):
    from czjLLM.prompt_pipeline.task_fingerprint import fingerprint_task

    namespace = {"__name__": "dynamic_task", "RULE": "safe"}
    exec("def template(content):\n    " + body, namespace)
    with pytest.raises(ValueError, match="dynamic task template namespace access"):
        fingerprint_task({"template": namespace["template"]})
