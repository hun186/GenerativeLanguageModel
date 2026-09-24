import json
from types import SimpleNamespace

from czjLLM.es_mode.adapters import elasticsearch_adapter as adapter_module
from czjLLM.es_mode.adapters.elasticsearch_adapter import ElasticsearchAdapter
from czjLLM.es_mode.entry import steps_es


def test_resolve_es_connection_uses_adapter_connect_and_propagates_transport(monkeypatch):
    created = []

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            created.append(self)

        def info(self):
            return {"version": {"number": "7-test"}}

    cfg = {
        "hosts": ["https://es.test.invalid:9200"],
        "es_user": "test-user",
        "es_pass": "test-pass",
        "es_index": "source",
        "es_src_index": "source",
        "es_tgt_index": "target",
        "id_col": "_id",
        "input_col": "rawInfo.content",
        "output_col": "analysis",
        "timeout": 17,
        "es_ca_certs": "/test/ca.pem",
        "es_verify_certs": True,
        "es_ssl_assert_hostname": True,
    }
    monkeypatch.setattr(steps_es, "load_es_cfg", lambda *args, **kwargs: cfg)
    monkeypatch.setattr(adapter_module, "Elasticsearch", FakeClient)

    ctx = SimpleNamespace(primary_key="_id")
    adapter, returned_cfg = steps_es.resolve_es_connection(
        ctx,
        lambda _name, default=None: default,
        SimpleNamespace(config="test"),
    )

    assert isinstance(adapter, ElasticsearchAdapter)
    assert returned_cfg is cfg
    assert adapter.es is created[0]
    assert created[0].kwargs == {
        "hosts": cfg["hosts"],
        "http_auth": ("test-user", "test-pass"),
        "timeout": 17,
        "max_retries": 3,
        "retry_on_timeout": True,
        "ca_certs": "/test/ca.pem",
        "verify_certs": True,
        "ssl_assert_hostname": True,
    }


class FakeIndices:
    def __init__(self):
        self.mappings = {"source": {}, "target": {}}
        self.put_calls = []

    def exists(self, index):
        return index in self.mappings

    def create(self, index, body):
        self.mappings[index] = dict(body["mappings"].get("properties", {}))

    def get_mapping(self, index):
        return {index: {"mappings": {"properties": self.mappings[index]}}}

    def put_mapping(self, index, body):
        self.put_calls.append((index, body))
        self.mappings[index].update(body.get("properties", {}))


def test_ensure_schemas_applies_configured_mapping_through_adapter(tmp_path):
    mapping_file = tmp_path / "mapping.json"
    mapping_file.write_text(
        json.dumps({"properties": {"configured_field": {"type": "keyword"}}}),
        encoding="utf-8",
    )
    indices = FakeIndices()
    adapter = ElasticsearchAdapter(
        {
            "src_index": "source",
            "tgt_index": "target",
            "es_apply_mapping": True,
            "mapping_file": str(mapping_file),
            "rerun": {},
        }
    )
    adapter.es = SimpleNamespace(indices=indices)
    ctx = SimpleNamespace(
        output_col="analysis",
        es_output_type="OBJECT",
        es_meta_type="OBJECT",
        es_writeback_rules=[],
    )

    steps_es.ensure_schemas_es(ctx, adapter, columns=[])

    assert indices.put_calls[0] == (
        "target",
        {"properties": {"configured_field": {"type": "keyword"}}},
    )
    assert indices.mappings["target"]["configured_field"] == {"type": "keyword"}
    # The existing fallback behavior remains active alongside predefined mappings.
    assert indices.mappings["target"]["analysis"] == {"type": "object"}
    assert indices.mappings["target"]["analysis_meta"]["type"] == "object"
