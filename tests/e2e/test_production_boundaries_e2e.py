from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from czjLLM.es_mode.adapters.elasticsearch_adapter import ElasticsearchAdapter
from czjLLM.es_mode.runtime.sinks.es_sink import ESSink
from czjLLM.prompt_pipeline.pipeline_controller import PromptAPIPipeline, call_llm_api
from czjLLM.prompt_pipeline.dispatch_parallelism import attach_execution_budget
from czjLLM.sql_mode.adapters.sqlite_adapter import SQLiteAdapter
from czjLLM.sql_mode.runtime.sinks.sql_sink import SqlSink
from czjLLM.tabular_mode.runtime.sinks.csv_sink import CSVSink
from .fake_es import InMemoryES, bulk, scan

pytestmark = pytest.mark.e2e


def llm(server, prompt, output=""):
    result = PromptAPIPipeline(
        task="E2E",
        content=prompt,
        OutputSaveFN=output,
        model_spec=server.model_spec,
        PGMSubDir=str(server.work_dir),
    ).proc()
    assert result["ok"], result
    return result["output"]


def test_txt_filesystem_through_real_openai_client(fake_openai, tmp_path):
    source = tmp_path / "input.txt"
    result = tmp_path / "final.txt"
    source.write_text("E2E_SUMMARY alpha", encoding="utf-8")
    value = llm(fake_openai, source.read_text(encoding="utf-8"), str(result))
    assert result.read_text(encoding="utf-8") == value
    assert value.startswith("SUMMARY::")
    assert fake_openai.requests[0]["body"]["model"] == "e2e-model"


def test_csv_identity_and_real_sink(fake_openai, sink_ctx, tmp_path):
    path = tmp_path / "rows.csv"
    pd.DataFrame({"id": ["csv-001", "csv-002"], "body": ["a", "b"], "analysis": ["", ""]}).to_csv(path, index=False)
    sink = CSVSink(sink_ctx, main_csv=str(path), flush_main_every=1)
    sink.open()
    for pk in ("csv-001", "csv-002"):
        sink.write_main(pk, llm(fake_openai, f"ROW_ID={pk}"))
    sink.close()
    rows = pd.read_csv(path).set_index("id")
    assert rows.loc["csv-001", "analysis"] == "RESULT::csv-001"
    assert rows.loc["csv-002", "analysis"] == "RESULT::csv-002"


def _sql_context(db):
    return SimpleNamespace(
        sqlite_path=str(db), is_sqlite=True, target_table="results", sql_table="source",
        primary_key="id", output_col="analysis", input_col="body", record_update_time=False,
    )


def test_sqlite_pending_query_and_real_sink_preserve_identity(fake_openai, tmp_path):
    db = tmp_path / "rows.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE source(id TEXT PRIMARY KEY, body TEXT)")
        conn.execute("CREATE TABLE results(id TEXT PRIMARY KEY, analysis TEXT)")
        conn.executemany("INSERT INTO source VALUES (?, ?)", [("sql-001", "alpha"), ("sql-002", "beta"), ("sql-003", "gamma")])
        conn.execute("INSERT INTO results VALUES ('sql-002', 'already-done')")
    cfg = {"server": str(db)}
    adapter = SQLiteAdapter(cfg).connect()
    selected = list(adapter.select_pending_rows(src_table="source", tgt_table="results", pk="id", input_col="body", output_cols=["analysis"], record_update_time=False))
    adapter.close()
    sink = SqlSink(_sql_context(db), is_sqlite=True); sink.open()
    for pk, _text, _extra in selected:
        sink.write_main(pk, llm(fake_openai, f"ROW_ID={pk}"))
    sink.close()
    with sqlite3.connect(db) as conn:
        actual = dict(conn.execute("SELECT id, analysis FROM results"))
    assert {row[0] for row in selected} == {"sql-001", "sql-003"}
    assert actual == {"sql-001": "RESULT::sql-001", "sql-002": "already-done", "sql-003": "RESULT::sql-003"}


def _patch_es(monkeypatch, adapter_module, sink_module, store):
    monkeypatch.setattr(adapter_module, "helpers", SimpleNamespace(scan=lambda **kw: scan(store, **kw)))
    monkeypatch.setattr(sink_module, "helpers", SimpleNamespace(bulk=lambda _client, actions, **_kw: bulk(store, actions)))


@pytest.mark.parametrize("dual", [False, True], ids=["single-index", "dual-index"])
def test_elasticsearch_real_adapter_and_sink(fake_openai, sink_ctx, monkeypatch, dual):
    import czjLLM.es_mode.adapters.elasticsearch_adapter as adapter_module
    import czjLLM.es_mode.runtime.sinks.es_sink as sink_module
    src, tgt = ("source-index", "result-index") if dual else ("records", "records")
    store = {src: {"es-101": {"rawInfo": {"content": "alpha"}}, "es-102": {"rawInfo": {"content": "beta"}, **({} if dual else {"analysis": "already-done"})}, "es-103": {"rawInfo": {"content": ""}}}}
    if dual:
        store[tgt] = {"es-102": {"analysis": "already-done"}}
    _patch_es(monkeypatch, adapter_module, sink_module, store)
    cfg = {"src_index": src, "tgt_index": tgt, "id_col": "_id", "input_col": "rawInfo.content", "output_col": "analysis", "rerun": {}}
    adapter = ElasticsearchAdapter(cfg); adapter.es = InMemoryES(store)
    selected = list(adapter.select_pending_rows(src_table=src, tgt_table=tgt, pk="_id", input_col="rawInfo.content", output_cols=["analysis"]))
    sink_ctx._es_adapter = adapter
    sink = ESSink(sink_ctx, adapter.es, tgt, output_col="analysis", flush_every=100, meta_field=None)
    sink.open()
    for pk, _text, _extra in selected:
        sink.write_main(pk, llm(fake_openai, f"ROW_ID={pk}"))
    sink.close()
    assert [row[0] for row in selected] == ["es-101"]
    assert store[tgt]["es-101"]["analysis"] == "RESULT::es-101"
    assert store[tgt]["es-102"]["analysis"] == "already-done"
    if dual:
        assert "analysis" not in store[src]["es-101"]


def _dispatch_ctx(fake_openai, tmp_path, *, capacity=None, slice_parallelism=8):
    values = dict(
        task="E2E",
        model_spec=fake_openai.model_spec,
        model_spec_name="e2e-model",
        removeFinPromptFile=True,
        max_tokens=64,
        PGMSubDir=str(tmp_path),
        mp_for_all_call=True,
        mp_debug=False,
        n_process=2,
        slice_parallelism=slice_parallelism,
        llm_call_audit_run_id="",
        llm_call_audit_path="",
    )
    if capacity is not None:
        values["execution_budget_capacity"] = capacity
    ctx = SimpleNamespace(**values)
    attach_execution_budget(ctx)
    return ctx


def _todo_item(root, name, count):
    item = root / name
    (item / "TODO").mkdir(parents=True)
    (item / "Success").mkdir()
    for number in range(count):
        (item / "TODO" / f"{number:04d}.txt").write_text(
            f"ROW_ID={name}-{number}", encoding="utf-8"
        )
    return item


def test_production_dispatch_http_concurrency_obeys_capacity_two(fake_openai, tmp_path):
    fake_openai.delay = 0.08
    ctx = _dispatch_ctx(fake_openai, tmp_path, capacity=2)
    item = _todo_item(tmp_path, "budget-two", 8)
    call_llm_api([str(item)], ctx)
    assert not list((item / "TODO").glob("*.txt"))
    assert len(list((item / "Success").glob("*.txt"))) == 8
    assert fake_openai.peak_active_requests <= 2
    snapshot = ctx._execution_budget.snapshot()
    assert snapshot.peak_in_use <= 2
    assert snapshot.in_use == 0


def test_deterministic_route_and_round_responses(fake_openai):
    assert llm(fake_openai, "E2E_ROUTE_FIN") == "FIN"
    assert llm(fake_openai, "E2E_ROUTE_LEGAL") == "LEGAL"
    assert llm(fake_openai, "E2E_ROUND2 prepared-a\nprepared-b\n").startswith("REDUCED::")


def test_openai_transport_retries_injected_transient_failure(fake_openai):
    fake_openai.fail_first("E2E_RETRY", count=1)
    assert llm(fake_openai, "E2E_RETRY ROW_ID=retry-001") == "RESULT::retry-001"
    matching = [r for r in fake_openai.requests if "E2E_RETRY" in str(r["body"])]
    assert [r["status"] for r in matching] == [500, 200]
    assert all(r["matched_rule"] in {"E2E_RETRY", None} for r in matching)


def test_production_dispatch_derived_capacity_eight_is_shared(fake_openai, tmp_path):
    fake_openai.delay = 0.08
    ctx = _dispatch_ctx(fake_openai, tmp_path, slice_parallelism=8)
    budget = ctx._execution_budget
    assert budget.capacity == 8
    first = _todo_item(tmp_path, "wide-a", 8)
    call_llm_api([str(first)], ctx)
    assert 2 < fake_openai.peak_active_requests <= 8

    fake_openai.peak_active_requests = 0
    second = _todo_item(tmp_path, "wide-b", 8)
    third = _todo_item(tmp_path, "wide-c", 8)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(call_llm_api, [str(second)], ctx),
            pool.submit(call_llm_api, [str(third)], ctx),
        ]
        for future in futures:
            future.result()
    assert fake_openai.peak_active_requests <= 8
    assert all(len(list((item / "Success").glob("*.txt"))) == 8 for item in (second, third))
    assert budget.snapshot().in_use == 0
