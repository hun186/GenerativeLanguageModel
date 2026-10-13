"""Issue #211: offline SQL/Excel integration through real scheduler and sinks.

Only the OpenAI-compatible HTTP boundary and deterministic *tokenizer cut
points* are simulated. Input files, production orchestrator, prompt queue,
stage merge/manifest, SQLite and Excel writes/readback are real. The mocked
tokenizer changes segmentation, not LLM dispatch, merge or persistence.
"""
from __future__ import annotations

import json
import sqlite3
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
