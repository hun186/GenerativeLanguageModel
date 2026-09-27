from types import SimpleNamespace

from czjLLM.es_mode.collection import ElasticsearchAggregateSink, ElasticsearchCollectionAdapter
from czjLLM.reduction import AggregateOutput


class FakeES:
    def __init__(self): self.documents = {}
    def update(self, *, index, id, body):
        assert body["doc_as_upsert"] is True
        self.documents[(index, id)] = body["doc"]
        return {"_id": id}


def scan_for(hits):
    def scan(**kwargs):
        assert kwargs["query"] == {"query": {"match_all": {}}}
        return iter(hits)
    return scan


def hit(id, text, day="2026-09-24", seq=1, stable=None):
    source = {"text": text, "day": day}
    if stable is not None: source["stable"] = stable
    return {"_id": id, "_source": source, "_seq_no": seq, "_primary_term": 2}


def snapshot(hits, **kwargs):
    adapter = SimpleNamespace(es=FakeES(), cfg={"hosts": ["https://secret"], "http_auth": ("u", "p")})
    return ElasticsearchCollectionAdapter(adapter, source_alias="search", scan=scan_for(hits)).snapshot(
        collection_id="docs", index="source", query={"query": {"match_all": {}}}, payload_paths=("text",), **kwargs
    )


def test_es_snapshot_default_identity_payload_version_order_and_secrets():
    one = snapshot([hit("b", "B", seq=2), hit("a", "A", seq=1)])[0]
    two = snapshot([hit("a", "A", seq=1), hit("b", "B", seq=2)])[0]
    assert [u.logical_id for u in one.units] == ["a", "b"]
    assert one.units[0].payload["text"] == "A"
    assert dict(one.units[0].provenance["source_version"]) == {"seq_no": 1, "primary_term": 2}
    assert one.fingerprint == two.fingerprint
    assert "hosts" not in str(one.to_mapping()) and "http_auth" not in str(one.to_mapping())


def test_es_custom_identity_grouping_and_changed_membership():
    grouped = snapshot([hit("1", "A", stable="business-a"), hit("2", "B", "2026-09-25", stable="business-b")], identity_path="stable", group_paths=("day",))
    assert len(grouped) == 2
    assert {m.units[0].logical_id for m in grouped} == {"business-a", "business-b"}
    assert snapshot([hit("1", "A")])[0].fingerprint != snapshot([hit("1", "changed")])[0].fingerprint


def test_es_aggregate_retry_reuses_same_document_id():
    manifest = snapshot([hit("1", "A")])[0]
    output = AggregateOutput(manifest, "daily-summary", {"answer": 1})
    client = FakeES(); sink = ElasticsearchAggregateSink(client, index="aggregates")
    sink.upsert(output); sink.upsert(output)
    assert list(client.documents) == [("aggregates", output.aggregate_output_id)]
    assert client.documents[("aggregates", output.aggregate_output_id)]["manifest_fingerprint"] == manifest.fingerprint
