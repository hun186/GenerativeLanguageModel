"""L1 persisted SQLite reuse through the production scheduler."""

import json
import copy
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from czjLLM.handlers import handle_data_mode as data_handler
from czjLLM.job_manager.job_config import LLMJobConfig
from czjLLM.prompt_pipeline.dispatch_parallelism import attach_execution_budget
from czjLLM.sql_mode.adapters.sqlite_adapter import SQLiteAdapter
from czjLLM.sql_mode.collection import SQLCollectionAdapter, SQLCollectionQuery
from czjLLM.sql_mode.entry import steps as sql_steps
from czjLLM.reduction.persisted_freshness import bind_persisted_execution_fingerprint

pytestmark = pytest.mark.e2e

def test_sql_persisted_result_reuse_semantic_refresh_and_collection(fake_openai, tmp_path, monkeypatch):
    db = tmp_path / "reuse.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE source(id TEXT PRIMARY KEY, body TEXT)")
        conn.execute("CREATE TABLE results(id TEXT PRIMARY KEY, document_summary TEXT, processing_fp TEXT)")
        conn.executemany("INSERT INTO source VALUES (?, ?)", [("A", "ROW_ID=A"), ("B", "ROW_ID=B")])
        conn.executemany("INSERT INTO results VALUES (?, ?, ?)", [("A", "REUSED-A", None), ("B", "OLD-B", "0" * 64)])
    cfg = {"server": str(db), "table_name": "source", "target_table": "results", "primary_key": "id",
           "input_col": "body", "output_col": "document_summary", "reset_output": False,
           "semantic_freshness": {"enabled": True, "execution_fingerprint": "auto", "processing_identity_column": "processing_fp"}}
    class SnapshotAdapter(SQLiteAdapter):
        # Model a pending snapshot obtained before another worker completed A;
        # dispatch-time authoritative recheck must save the request.
        def select_pending_rows(self, **kwargs):
            for row in self.conn.execute("SELECT id, body FROM source ORDER BY id"):
                yield row[0], row[1], {}
    monkeypatch.setattr(sql_steps, "SQLiteAdapter", SnapshotAdapter)
    monkeypatch.setattr(sql_steps, "load_sql_cfg", lambda ctx, get_param, args, policy: cfg)
    ctx = LLMJobConfig(); ctx.mode = "sql"; ctx.task = "ROW_ID echo"; ctx.model_spec = fake_openai.model_spec
    ctx.model_spec_name = "e2e-model"; ctx.max_tokens = 64; ctx.PGMSubDir = str(tmp_path)
    ctx.prompt_dir = str(tmp_path / "prompts"); ctx.llm_source_dir = str(tmp_path / "work")
    ctx.llm_source_finished_dir = str(tmp_path / "finished"); ctx.log_dir = str(tmp_path / "logs")
    ctx.n_process = 1; ctx.slice_parallelism = 1; ctx.schedule_todo_wait_seconds = 5
    ctx.pending_running_all_deferred_wait_seconds = 0; ctx.reduction = {"enabled": False, "profile": "concat_text"}
    expected = bind_persisted_execution_fingerprint(ctx, SimpleNamespace(cfg=copy.deepcopy(cfg)))
    assert expected and expected != "auto"
    # Simulate A being completed by another worker after the candidate snapshot.
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE results SET processing_fp=? WHERE id='A'", (expected,))
    for directory in (ctx.prompt_dir, ctx.llm_source_dir, ctx.llm_source_finished_dir, ctx.log_dir): Path(directory).mkdir(parents=True, exist_ok=True)
    attach_execution_budget(ctx)
    params = {"input_col": "body", "output_col": "document_summary", "record_update_time": False,
              "flatten_json_output": False, "allowed_output_fields": [], "save_raw_input_when_flatten": False}
    data_handler.handle_data_mode(ctx, lambda name, default=None: params.get(name, default), SimpleNamespace(config="offline-e2e"))
    with sqlite3.connect(db) as conn:
        rows = dict((row[0], row[1:]) for row in conn.execute("SELECT id, document_summary, processing_fp FROM results"))
    assert rows["A"] == ("REUSED-A", expected)
    assert rows["B"] == ("RESULT::B\n", expected)
    assert len(fake_openai.requests) == 1
    assert ctx._producer_actual_scheduled_rows == 1
    adapter = SQLiteAdapter(cfg).connect()
    manifest = SQLCollectionAdapter(adapter, source_alias="results").snapshot(collection_id="daily", query=SQLCollectionQuery(
        "SELECT id, document_summary, processing_fp FROM results", (), "id", ("document_summary",), processing_identity_field="processing_fp"))[0]
    assert [unit.payload["document_summary"] for unit in manifest.units] == ["REUSED-A", "RESULT::B\n"]
    assert all(not adapter.is_row_pending(tgt_table="results", pk="id", pk_value=key, output_cols=["document_summary"]) for key in ("A", "B"))
    adapter.close()
    events = [json.loads(line) for line in (tmp_path / "logs/pending_recheck_events.jsonl").read_text().splitlines()]
    assert any(e["pk"] == "A" and e["reason"] == "fresh_completed" and e["decision"] == "skip" for e in events)
    assert any(e["pk"] == "B" and e["reason"] == "execution_fingerprint_mismatch" for e in events)
    serialized = json.dumps(events)
    assert "e2e-dummy-key" not in serialized and fake_openai.base_url not in serialized
