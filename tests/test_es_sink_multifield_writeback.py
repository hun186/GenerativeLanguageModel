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


def test_es_sink_resolves_business_key_to_real_es_id_before_bulk(monkeypatch):
    captured = {}
    fake_es = types.ModuleType("elasticsearch")
    fake_es.Elasticsearch = object

    def fake_bulk(es, actions, **kwargs):
        captured["actions"] = list(actions)
        return len(captured["actions"]), []

    fake_es.helpers = types.SimpleNamespace(bulk=fake_bulk)
    monkeypatch.setitem(sys.modules, "elasticsearch", fake_es)
    sys.modules.pop("czjLLM.es_mode.runtime.sinks.es_sink", None)
    mod = importlib.import_module("czjLLM.es_mode.runtime.sinks.es_sink")

    class SearchES(DummyES):
        def search(self, index, body, request_timeout=None):
            captured["search"] = {"index": index, "body": body, "request_timeout": request_timeout}
            return {"hits": {"hits": [{"_id": "real-es-doc-id"}]}}

    adapter = SimpleNamespace(
        cfg={"id_col": "sha1", "pk_keyword_suffix": ".keyword"},
        get_field_mapping=lambda index, field: {"fields": {"keyword": {}}},
    )
    ctx = SimpleNamespace(
        output_col="main_result",
        output_profile="json",
        es_refresh_after_flush=False,
        es_request_timeout=12,
        _es_adapter=adapter,
    )
    sink = mod.ESSink(ctx, SearchES(), index="docs", output_col="main_result", flush_every=999)

    sink.write_main("business-key-1", {"ok": True})
    sink.flush_all()

    assert captured["search"]["body"]["query"] == {"term": {"sha1.keyword": "business-key-1"}}
    assert captured["actions"][0]["_id"] == "real-es-doc-id"
    assert captured["actions"][0]["doc"]["main_result"] == {"ok": True}
    assert captured["actions"][0]["doc"]["sha1"] == "business-key-1"


def test_es_sink_bulk_errors_raise_and_keep_buffer(monkeypatch):
    fake_es = types.ModuleType("elasticsearch")
    fake_es.Elasticsearch = object

    def fake_bulk(es, actions, **kwargs):
        list(actions)
        return 0, [{"update": {"status": 400, "error": {"type": "document_parsing_exception"}}}]

    fake_es.helpers = types.SimpleNamespace(bulk=fake_bulk)
    monkeypatch.setitem(sys.modules, "elasticsearch", fake_es)
    sys.modules.pop("czjLLM.es_mode.runtime.sinks.es_sink", None)
    mod = importlib.import_module("czjLLM.es_mode.runtime.sinks.es_sink")

    ctx = SimpleNamespace(output_col="main_result", output_profile="json", es_refresh_after_flush=False)
    sink = mod.ESSink(ctx, DummyES(), index="docs", output_col="main_result", flush_every=999)
    sink.write_main("doc-1", {"ok": True})

    try:
        sink.flush_all()
    except RuntimeError as exc:
        assert "ESSink bulk update failed" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError for ES bulk errors")

    assert len(sink._buffer) == 1
    sink._buffer.clear()
