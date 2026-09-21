import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from czjLLM.handlers import handle_data_mode as data_handler
from czjLLM.job_manager.job_config import LLMJobConfig
from czjLLM.prompt_pipeline.dispatch_parallelism import attach_execution_budget
from czjLLM.sql_mode.adapters.sqlite_adapter import SQLiteAdapter


pytestmark = pytest.mark.e2e


class RecordingSQLiteAdapter(SQLiteAdapter):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.selected = []

    def select_pending_rows(self, **kwargs):
        for row in super().select_pending_rows(**kwargs):
            self.selected.append(str(row[0]))
            yield row


def test_handle_data_mode_sql_backend_runs_production_scheduler(
    fake_openai, tmp_path, monkeypatch
):
    db = tmp_path / "backend.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE source(id TEXT PRIMARY KEY, body TEXT)")
        conn.execute("CREATE TABLE results(id TEXT PRIMARY KEY, analysis TEXT)")
        conn.executemany(
            "INSERT INTO source VALUES (?, ?)",
            [("sql-e2e-001", "ROW_ID=sql-e2e-001"), ("sql-e2e-002", "ROW_ID=sql-e2e-002")],
        )
    cfg = {
        "server": str(db), "table_name": "source", "target_table": "results",
        "primary_key": "id", "input_col": "body", "output_col": "analysis",
        "reset_output": False,
    }
    adapter = RecordingSQLiteAdapter(cfg)
    monkeypatch.setattr(
        data_handler,
        "resolve_connection",
        lambda ctx, get_param, args: (adapter, True, cfg),
    )

    ctx = LLMJobConfig()
    ctx.mode = "sql"
    ctx.task = "ROW_ID echo"
    ctx.model_spec = fake_openai.model_spec
    ctx.model_spec_name = "e2e-model"
    ctx.max_tokens = 64
    ctx.PGMSubDir = str(tmp_path)
    ctx.prompt_dir = str(tmp_path / "prompts")
    ctx.llm_source_dir = str(tmp_path / "work")
    ctx.llm_source_finished_dir = str(tmp_path / "finished")
    ctx.log_dir = str(tmp_path / "logs")
    ctx.sqlite_path = str(db)
    ctx.is_sqlite = True
    ctx.n_process = 2
    ctx.slice_parallelism = 2
    ctx.schedule_todo_wait_seconds = 5
    ctx.pending_running_all_deferred_wait_seconds = 0
    ctx.reduction = {"enabled": False, "profile": "concat_text"}
    for directory in (ctx.prompt_dir, ctx.llm_source_dir, ctx.llm_source_finished_dir, ctx.log_dir):
        Path(directory).mkdir(parents=True, exist_ok=True)
    attach_execution_budget(ctx)

    params = {
        "input_col": "body", "output_col": "analysis", "record_update_time": False,
        "flatten_json_output": False, "allowed_output_fields": [],
        "save_raw_input_when_flatten": False,
    }
    get_param = lambda name, default=None: params.get(name, default)
    data_handler.handle_data_mode(ctx, get_param, SimpleNamespace(config="offline-e2e"))

    with sqlite3.connect(db) as conn:
        written = dict(conn.execute("SELECT id, analysis FROM results"))
    expected = {"sql-e2e-001", "sql-e2e-002"}
    requested = {
        marker
        for request in fake_openai.requests
        for marker in expected
        if f"ROW_ID={marker}" in str(request["body"])
    }
    assert set(adapter.selected) == requested == set(written)
    assert written == {key: f"RESULT::{key}\n" for key in expected}
    assert ctx._execution_budget.snapshot().in_use == 0
