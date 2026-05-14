from types import SimpleNamespace

import pytest
pytest.importorskip("elasticsearch")

from czjLLM.es_mode.runtime.sinks.es_sink import ESSink
from czjLLM.es_mode.entry.steps_es import choose_columns_es
from czjLLM.es_mode.adapters.elasticsearch_adapter import ElasticsearchAdapter


class DummyIndices:
    def exists(self, index):
        return True

    def refresh(self, index):
        return None


class DummyES:
    indices = DummyIndices()


class DummyAdapter:
    def __init__(self):
        self.cfg = {
            "id_col": "_id",
            "input_col": "rawInfo.content",
            "output_col": "legacy_output",
            "src_index": "src",
            "tgt_index": "tgt",
        }


def test_choose_columns_es_prefers_main_yaml_and_registers_es_writeback_rules():
    ctx = SimpleNamespace()
    args = SimpleNamespace(id_col=None)
    adapter = DummyAdapter()
    cfg = {
        "input_col": "rawInfo.title",
        "output_col": "main_result",
        "record_update_time": True,
        "es_writeback_rules": [
            {"output_col": "route_result", "source": "stage", "stage": "route", "output_type": "keyword"},
            {"output_col": "main_result", "source": "stage", "stage": "extract", "output_type": "nested"},
        ],
        "es_payload_date_normalize_fields": ["main_result"],
        "es_flatten_writeback_rules": [{"writeback_rule": 0, "enabled": True}],
        "flatten_json_output": True,
    }

    columns = choose_columns_es(ctx, {"adapter": adapter}, cfg.get, args)

    assert ctx.input_col == "rawInfo.title"
    assert ctx.output_col == "main_result"
    assert ctx.output_cols == ["main_result", "route_result"]
    assert ctx.sql_writeback_rules == ctx.es_writeback_rules
    assert adapter.cfg["output_cols"] == ["main_result", "route_result"]
    assert ctx.flatten_json_output is False
    assert ctx.sql_flatten_writeback_rules == []
    assert ("route_result", "keyword") in columns
    assert ("main_result", "nested") in columns


def test_es_sink_multifield_writeback_routes_fields_to_rule_indexes_and_meta():
    ctx = SimpleNamespace(
        output_col="main_result",
        record_update_time=True,
        es_refresh_after_flush=False,
        es_writeback_rules=[
            {"output_col": "route_result", "index": "audit-index", "write_meta": False},
            {"output_col": "main_result", "index": "main-index", "meta_field": "main_meta"},
        ],
        task="demo-task",
        channel="demo-channel",
        source="unit-test",
    )
    sink = ESSink(ctx, DummyES(), index="default-index", output_col="main_result", flush_every=999)

    sink.write_main("doc-1", {"route_result": "zh", "main_result": '[{"x": 1}]'})

    assert len(sink._buffer) == 2
    by_index = {item["_index"]: item["doc"] for item in sink._buffer}
    assert by_index["audit-index"] == {"route_result": "zh", "update_time_ai": by_index["audit-index"]["update_time_ai"]}
    assert by_index["main-index"]["main_result"] == [{"x": 1}]
    assert by_index["main-index"]["main_meta"]["output_field"] == "main_result"


def test_adapter_single_index_returns_extra_stage_source_inputs(monkeypatch):
    adapter = ElasticsearchAdapter({
        "es_request_timeout": 1,
        "es_scroll_keepalive": "1m",
        "stage_source_input_cols": ["rawInfo.title"],
    })
    adapter.es = SimpleNamespace(
        search=lambda *a, **k: {"hits": {"hits": [{"_id": "1", "_source": {"rawInfo": {"content": "body"}}}]}},
    )
    monkeypatch.setattr(
        "czjLLM.es_mode.adapters.elasticsearch_adapter.helpers.scan",
        lambda **kwargs: iter([
            {
                "_id": "1",
                "_source": {
                    "rawInfo": {"content": "body", "title": "title"},
                },
            }
        ]),
    )
    monkeypatch.setattr(adapter, "_is_fresh_output", lambda src, output_col: False)

    rows = list(
        adapter.select_pending_rows(
            src_table="idx",
            tgt_table="idx",
            pk="_id",
            input_col="rawInfo.content",
            output_col="main_result",
            record_update_time=False,
            fetch_size=10,
        )
    )

    assert rows == [("1", "body", {"rawInfo.title": "title"})]
