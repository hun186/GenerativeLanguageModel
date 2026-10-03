import json
import sqlite3
import sys
import types
import importlib.util
import pytest
from pathlib import Path
from types import SimpleNamespace

sys.modules.setdefault("czjLLM.job_manager.console_ui", types.SimpleNamespace(
    tlog=lambda *_: None, tlog_warn=lambda *_: None, tlog_ok=lambda *_: None,
))
sys.modules.setdefault("pyodbc", types.SimpleNamespace(connect=lambda *_args, **_kwargs: None))
_tqdm = types.ModuleType("tqdm")
_tqdm.write = lambda *_args, **_kwargs: None
_tqdm.tqdm = lambda value=None, **_kwargs: value
sys.modules.setdefault("tqdm", _tqdm)
sys.modules.setdefault("tqdm.contrib", types.ModuleType("tqdm.contrib"))
sys.modules.setdefault("tqdm.contrib.logging", types.SimpleNamespace(logging_redirect_tqdm=lambda: None))

from czjLLM.common.pending_decision import PendingDecision
from czjLLM.sql_mode.adapters.sqlite_adapter import SQLiteAdapter
from czjLLM.sql_mode.adapters.pending_freshness import validate_processing_identity_column
from czjLLM.sql_mode.schema.schema_ops import ensure_main_schema
from czjLLM.sql_utils.row_utils import upsert_multi_values
_spec = importlib.util.spec_from_file_location("pending_recheck_l1", Path(__file__).parents[3] / "czjLLM/sql_mode/runtime/pending_recheck.py")
pending_recheck = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pending_recheck)


def _adapter(tmp_path):
    path = tmp_path / "freshness.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript("""
      CREATE TABLE src (id TEXT PRIMARY KEY, body TEXT);
      CREATE TABLE tgt (id TEXT PRIMARY KEY, result TEXT, processing_fp TEXT);
      INSERT INTO src VALUES ('fresh','a'),('missing','b'),('stale','c'),('blank','d');
      INSERT INTO tgt VALUES ('fresh','old','expected'),('missing','old',NULL),
                             ('stale','old','previous'),('blank',NULL,'expected');
    """)
    conn.commit(); conn.close()
    adapter = SQLiteAdapter({"server": str(path), "semantic_freshness": {
        "execution_fingerprint": "expected", "processing_identity_column": "processing_fp"}})
    adapter.connect()
    return adapter


def test_sql_strict_discovery_and_recheck_share_semantics(tmp_path):
    adapter = _adapter(tmp_path)
    try:
        assert adapter.check_row_pending(tgt_table="tgt", pk="id", pk_value="fresh", output_cols=["result"]).reason == "fresh_completed"
        assert adapter.check_row_pending(tgt_table="tgt", pk="id", pk_value="missing", output_cols=["result"]).reason == "missing_processing_identity"
        assert adapter.check_row_pending(tgt_table="tgt", pk="id", pk_value="stale", output_cols=["result"]).reason == "execution_fingerprint_mismatch"
        assert adapter.check_row_pending(tgt_table="tgt", pk="id", pk_value="blank", output_cols=["result"]).reason == "missing_output"
        selected = [row[0] for row in adapter.select_pending_rows(src_table="src", tgt_table="tgt", pk="id", input_col="body", output_cols=["result"], record_update_time=False)]
        assert selected == ["missing", "stale", "blank"]
    finally:
        adapter.close()


def test_event_log_is_safe_bounded_and_stats_are_additive(tmp_path):
    adapter = _adapter(tmp_path)
    path = tmp_path / "events.jsonl"
    ctx = SimpleNamespace(_pending_adapter=adapter, _pending_tgt_table="tgt", primary_key="id",
        output_cols=["result"], pending_recheck_event_log_path=str(path),
        pending_recheck_event_log_max_bytes=1024, _pending_recheck_announced=True,
        api_key="DO-NOT-LOG", base_url="http://secret.invalid")
    try:
        assert pending_recheck.still_pending_before_dispatch(ctx, "fresh") is False
        assert pending_recheck.still_pending_before_dispatch(ctx, "stale") is True
        records = [json.loads(line) for line in path.read_text().splitlines()]
        assert [item["reason"] for item in records] == ["fresh_completed", "execution_fingerprint_mismatch"]
        assert len(records[1]["expected_execution_fingerprint"]) <= 12
        assert "DO-NOT-LOG" not in path.read_text() and "secret.invalid" not in path.read_text()
        stats = pending_recheck.pending_recheck_stats(ctx)
        assert stats["checked"] == 2 and stats["already_completed"] == 1
        assert stats["reasons"]["execution_fingerprint_mismatch"] == 1
        assert stats["semantic_stale_count"] == 1 and stats["skip_rate"] == .5
        for index in range(100):
            pending_recheck.record_pending_event(ctx, index, PendingDecision(False, "fresh_completed"))
        assert path.stat().st_size < 2048
        assert all(json.loads(line) for line in path.read_text().splitlines())
    finally:
        adapter.close()


@pytest.mark.parametrize("identity", ["ID", "body", "result", "audit", "expanded_name"])
def test_processing_identity_column_collision_fails_before_write(identity):
    ctx = SimpleNamespace(
        expected_execution_fingerprint="fp", processing_identity_column=identity,
        primary_key="id", input_col="body", output_col="result", output_cols=["result"],
        sql_writeback_rules=[{"output_col": "audit"}], sql_expand_json_to_columns=True,
        sql_expand_json_prefix="expanded_", allowed_output_fields=["name"],
    )
    with pytest.raises(ValueError, match="processing_identity_column"):
        validate_processing_identity_column(ctx)


def test_strict_schema_and_atomic_first_write_are_fresh_on_second_check(tmp_path):
    path = tmp_path / "schema.sqlite"
    adapter = SQLiteAdapter({"server": str(path), "semantic_freshness": {
        "execution_fingerprint": "current", "processing_identity_column": "processing_fp"}}).connect()
    adapter.ensure_table("source", "id")
    adapter.ensure_columns("source", [("body", "TEXT")])
    adapter.conn.execute('INSERT INTO source (id, body) VALUES (?, ?)', ("one", "text"))
    adapter.conn.commit()
    ctx = SimpleNamespace(
        target_table="results", sql_table="source", primary_key="id", input_col="body",
        output_col="result", output_cols=["result"], sql_writeback_rules=[],
        sql_expand_json_to_columns=False, record_update_time=False,
        expected_execution_fingerprint="current", processing_identity_column="processing_fp",
        is_sqlite=True, sqlite_path=str(path), sql_connection_string=None,
    )
    ensure_main_schema(ctx, adapter, ["id", "body"], {})
    assert {"result", "processing_fp"}.issubset(set(adapter.list_columns("results")))
    cursor = adapter.conn.cursor()
    upsert_multi_values(ctx, cursor, "one", {"result": "summary", "processing_fp": "current"}, True)
    adapter.conn.commit()
    assert adapter.check_row_pending(
        tgt_table="results", pk="id", pk_value="one", output_cols=["result"]
    ).reason == "fresh_completed"
    assert adapter.conn.execute(
        'SELECT result, processing_fp FROM results WHERE id=?', ("one",)
    ).fetchone() == ("summary", "current")
    adapter.close()


def test_recheck_logs_never_use_raw_task_prompt_as_identifier(tmp_path):
    event_path = tmp_path / "events.jsonl"
    skip_path = tmp_path / "skips.log"
    ctx = SimpleNamespace(
        task="SECRET RAW PROMPT\nwith sensitive instruction",
        pending_recheck_event_log_path=str(event_path),
        pending_recheck_skip_log_path=str(skip_path),
        output_cols=["result"],
    )
    pending_recheck.record_pending_event(
        ctx, "A", PendingDecision(False, "fresh_completed"))
    pending_recheck.record_pending_event(
        ctx, "B", PendingDecision(True, "execution_fingerprint_mismatch", {
            "expected_execution_fingerprint": "a" * 64,
            "persisted_execution_fingerprint": "b" * 64,
        }))
    pending_recheck.record_pending_skip(ctx, "A")
    combined = event_path.read_text() + skip_path.read_text()
    assert "SECRET RAW PROMPT" not in combined
    assert all(json.loads(line)["task_json"] == "unknown"
               for path in (event_path, skip_path) for line in path.read_text().splitlines())


def test_recheck_identifier_uses_only_bounded_config_basename(tmp_path):
    event_path = tmp_path / "events.jsonl"
    ctx = SimpleNamespace(
        config_path="/private/secret/path/job_config.json",
        pending_recheck_event_log_path=str(event_path),
        output_cols=["result"],
    )
    pending_recheck.record_pending_event(
        ctx, "A", PendingDecision(False, "fresh_completed"))
    text = event_path.read_text()
    assert json.loads(text)["task_json"] == "job_config.json"
    assert "/private/secret/path/" not in text
