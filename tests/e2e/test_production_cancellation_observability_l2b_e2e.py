"""One real SQL production cancellation/safe-drain E2E for L2b."""
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
from pathlib import Path
from threading import Event

import pytest

from czjLLM.job_manager.job_config import LLMJobConfig
from czjLLM.prompt_pipeline.dispatch_parallelism import attach_execution_budget
from czjLLM.reduction import ensure_production_observer, request_execution_cancel
from czjLLM.sql_mode.runtime.orchestrator import run_pipeline
from czjLLM.sql_mode.runtime.sinks.sql_sink import SqlSink

pytestmark = pytest.mark.e2e


def test_production_cancellation_and_observability_l2b(fake_openai, tmp_path):
    db = tmp_path / "cancel.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE results(id TEXT PRIMARY KEY, analysis TEXT)")

    ctx = LLMJobConfig()
    ctx.mode = "sql"
    ctx.task = "SECRET RAW PROMPT"
    ctx.stages = [
        {"name": "first", "task": "ROW_ID echo", "max_attempts": 1},
        {"name": "second", "task": "E2E_SUMMARY", "max_attempts": 1},
    ]
    ctx.model_spec = dict(fake_openai.model_spec, api_key="sk-very-secret-key")
    ctx.model_spec_name = "e2e-model"
    ctx.max_tokens = 128
    ctx.PGMSubDir = str(tmp_path)
    ctx.prompt_dir = str(tmp_path / "prompts")
    ctx.llm_source_dir = str(tmp_path / "work")
    ctx.llm_source_finished_dir = str(tmp_path / "finished")
    ctx.llm_source_backup_dir = str(tmp_path / "backup")
    ctx.log_dir = str(tmp_path / "logs")
    ctx.sqlite_path = str(db)
    ctx.sql_table = "source"
    ctx.target_table = "results"
    ctx.primary_key = "id"
    ctx.input_col = "body"
    ctx.output_col = "analysis"
    ctx.output_cols = ["analysis"]
    ctx.record_update_time = False
    ctx.flatten_json_output = False
    ctx.allowed_output_fields = []
    ctx.sql_enable_multistage_stream = True
    ctx.multistage_row_parallelism = 1
    ctx.n_process = 1
    ctx.slice_parallelism = 1
    ctx.schedule_todo_wait_seconds = 5
    ctx.pending_running_all_deferred_wait_seconds = 0
    ctx.cleanup_prompt_item_after_writeback = False
    ctx.reduction = {"enabled": False, "profile": "concat_text"}
    ctx.config_path = "safe-l2b.yaml"
    ctx.private_endpoint_hint = "https://private-endpoint.example"
    ctx.connection_hint = "Server=secret"
    for directory in (ctx.prompt_dir, ctx.llm_source_dir, ctx.llm_source_finished_dir,
                      ctx.llm_source_backup_dir, ctx.log_dir):
        Path(directory).mkdir(parents=True, exist_ok=True)
    attach_execution_budget(ctx)

    fake_openai.request_started = Event()
    fake_openai.release_response = Event()
    rows = [
        ("first", "ROW_ID=first", {"body": "ROW_ID=first"}),
        ("later", "SECRET RAW PROMPT Server=secret", {"body": "Server=secret"}),
    ]
    sink = SqlSink(ctx, is_sqlite=True)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(run_pipeline, ctx, rows, True, sink)
        assert fake_openai.request_started.wait(timeout=15)
        assert request_execution_cancel(ctx, source="e2e")
        fake_openai.release_response.set()
        pending.result(timeout=30)

    assert ctx.run_status == "cancelled"
    assert len(fake_openai.requests) == 1
    assert "ROW_ID=first" in str(fake_openai.requests[0]["body"])
    assert all("Server=secret" not in str(request["body"]) for request in fake_openai.requests)
    assert ctx._execution_budget.snapshot().in_use == 0
    with sqlite3.connect(db) as conn:
        assert list(conn.execute("SELECT * FROM results")) == []

    observer = ensure_production_observer(ctx)
    records = [json.loads(line) for line in observer.path.read_text(encoding="utf-8").splitlines()]
    events = {record["event"] for record in records}
    assert {"cancellation_requested", "run_cancelled"} <= events
    assert observer.snapshot()["run_status"] == "cancelled"
    serialized = json.dumps(records)
    for secret in ("SECRET RAW PROMPT", "sk-very-secret-key",
                   "https://private-endpoint.example", "Server=secret",
                   fake_openai.base_url, repr(ctx.model_spec)):
        assert secret not in serialized

    # Safe-drain phase: cancellation while an already-scheduled row owns the
    # deterministic writeback boundary must not set worker teardown early or
    # discard that completed leaf result.
    drain_db = tmp_path / "drain.sqlite"
    with sqlite3.connect(drain_db) as conn:
        conn.execute("CREATE TABLE results(id TEXT PRIMARY KEY, analysis TEXT)")
    drain = LLMJobConfig()
    for name in (
        "mode", "model_spec_name", "max_tokens", "n_process", "slice_parallelism",
        "schedule_todo_wait_seconds", "pending_running_all_deferred_wait_seconds",
        "record_update_time", "flatten_json_output", "cleanup_prompt_item_after_writeback",
    ):
        setattr(drain, name, getattr(ctx, name))
    drain.task = "ROW_ID echo"; drain.stages = []
    drain.model_spec = fake_openai.model_spec
    drain.PGMSubDir = str(tmp_path / "drain")
    drain.prompt_dir = str(tmp_path / "drain/prompts")
    drain.llm_source_dir = str(tmp_path / "drain/work")
    drain.llm_source_finished_dir = str(tmp_path / "drain/finished")
    drain.llm_source_backup_dir = str(tmp_path / "drain/backup")
    drain.log_dir = str(tmp_path / "drain/logs")
    drain.sqlite_path = str(drain_db); drain.target_table = "results"; drain.sql_table = "source"
    drain.primary_key = "id"; drain.input_col = "body"; drain.output_col = "analysis"
    drain.output_cols = ["analysis"]; drain.allowed_output_fields = []
    drain.reduction = {"enabled": False, "profile": "concat_text"}
    for directory in (drain.prompt_dir, drain.llm_source_dir, drain.llm_source_finished_dir,
                      drain.llm_source_backup_dir, drain.log_dir): Path(directory).mkdir(parents=True)
    attach_execution_budget(drain)
    write_started = Event(); release_write = Event()
    class BlockingSink(SqlSink):
        def write_main(self, *args, **kwargs):
            write_started.set(); release_write.wait(timeout=10)
            return super().write_main(*args, **kwargs)
    fake_openai.request_started = None; fake_openai.release_response = None
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(run_pipeline, drain, [("drain", "ROW_ID=drain", {"body": "ROW_ID=drain"})],
                              True, BlockingSink(drain, is_sqlite=True))
        assert write_started.wait(timeout=20)
        request_execution_cancel(drain, source="e2e")
        release_write.set()
        pending.result(timeout=30)
    assert drain.run_status == "cancelled"
    with sqlite3.connect(drain_db) as conn:
        assert dict(conn.execute("SELECT id, analysis FROM results"))["drain"] == "RESULT::drain\n"
