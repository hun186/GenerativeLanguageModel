import importlib
import sys
import types
from types import SimpleNamespace


def _load_es_sink_module(monkeypatch):
    try:
        has_elasticsearch = importlib.util.find_spec("elasticsearch") is not None
    except ValueError:
        has_elasticsearch = "elasticsearch" in sys.modules
    if not has_elasticsearch:
        fake_es = types.ModuleType("elasticsearch")
        fake_es.Elasticsearch = object
        fake_es.helpers = types.SimpleNamespace(bulk=lambda *args, **kwargs: (0, []))
        monkeypatch.setitem(sys.modules, "elasticsearch", fake_es)
    return importlib.import_module("czjLLM.es_mode.runtime.sinks.es_sink")


class DummyIndices:
    def exists(self, index):
        return True

    def refresh(self, index):
        return None


class DummyES:
    indices = DummyIndices()


def test_es_sink_multifield_writeback_uses_rule_indexes_and_meta(monkeypatch):
    mod = _load_es_sink_module(monkeypatch)
    ctx = SimpleNamespace(
        output_col="main_result",
        output_profile="json",
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
    sink = mod.ESSink(ctx, DummyES(), index="default-index", output_col="main_result", flush_every=999)

    sink.write_main("doc-1", {"route_result": "zh", "main_result": '[{"x": 1}]'})

    assert len(sink._buffer) == 2
    by_index = {item["_index"]: item["doc"] for item in sink._buffer}
    assert by_index["audit-index"]["route_result"] == "zh"
    assert "route_result_meta" not in by_index["audit-index"]
    assert by_index["main-index"]["main_result"] == [{"x": 1}]
    assert by_index["main-index"]["main_meta"]["output_field"] == "main_result"
    sink._buffer.clear()
