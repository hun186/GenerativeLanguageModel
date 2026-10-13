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
    ctx.removeFinPromptFile = False
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
def test_two_json_slices_write_one_valid_persisted_result(
    backend, fake_openai, tmp_path, monkeypatch,
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
