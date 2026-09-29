from types import SimpleNamespace

import pytest

from czjLLM.es_mode.collection import ElasticsearchAggregateSink, ElasticsearchCollectionAdapter
from czjLLM.reduction import AggregateOutput


class FakeES:
    def __init__(self): self.documents = {}
    def update(self, *, index, id, body):
        assert body["scripted_upsert"] is True
        params = body["script"]["params"]
        existing = self.documents.get((index, id))
        if existing is not None and any(
            existing[field] != params[field]
            for field in ("collection_id", "manifest_fingerprint", "output_key")
        ):
            raise ValueError("aggregate lineage conflict")
        self.documents[(index, id)] = params["document"]
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
    payload_paths = kwargs.pop("payload_paths", ("text",))
    return ElasticsearchCollectionAdapter(adapter, source_alias="search", scan=scan_for(hits)).snapshot(
        collection_id="docs", index="source", query={"query": {"match_all": {}}}, payload_paths=payload_paths, **kwargs
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
    assert {m.units[0].logical_id for m in grouped} == {"str:business-a", "str:business-b"}
    assert snapshot([hit("1", "A")])[0].fingerprint != snapshot([hit("1", "changed")])[0].fingerprint


def test_es_numeric_order_reserved_group_names_and_shuffled_fingerprint():
    ten = hit("ten", "ten"); ten["_source"].update(rank=10, created_at="2026-09-27", host="logical-a")
    two = hit("two", "two"); two["_source"].update(rank=2, created_at="2026-09-27", host="logical-a")
    first = snapshot([ten, two], payload_paths=("text", "rank"), order_paths=("rank",), group_paths=("created_at", "host"))[0]
    second = snapshot([two, ten], payload_paths=("text", "rank"), order_paths=("rank",), group_paths=("created_at", "host"))[0]
    assert [unit.payload["rank"] for unit in first.units] == [2, 10]
    assert list(first.provenance["group"]) == [
        {"field": "created_at", "value": "2026-09-27"},
        {"field": "host", "value": "logical-a"},
    ]
    assert first.fingerprint == second.fingerprint


def test_es_custom_identity_is_type_stable_and_rejects_structures():
    integer = snapshot([hit("a", "A", stable=1)], identity_path="stable")[0]
    string = snapshot([hit("a", "A", stable="1")], identity_path="stable")[0]
    boolean = snapshot([hit("a", "A", stable=True)], identity_path="stable")[0]
    assert [integer.units[0].logical_id, string.units[0].logical_id, boolean.units[0].logical_id] == ["int:1", "str:1", "bool:true"]
    for invalid in ({"nested": 1}, [1], None, "", float("nan"), float("inf")):
        with pytest.raises(ValueError, match="identity"):
            snapshot([hit("a", "A", stable=invalid)], identity_path="stable")


def test_es_aggregate_retry_reuses_same_document_id():
    manifest = snapshot([hit("1", "A")])[0]
    output = AggregateOutput(manifest, "daily-summary", {"answer": 1})
    client = FakeES(); sink = ElasticsearchAggregateSink(client, index="aggregates")
    sink.upsert(output); sink.upsert(output)
    assert list(client.documents) == [("aggregates", output.aggregate_output_id)]
    assert client.documents[("aggregates", output.aggregate_output_id)]["manifest_fingerprint"] == manifest.fingerprint


def test_es_aggregate_rejects_conflicting_persisted_lineage_atomically():
    manifest = snapshot([hit("1", "A")])[0]
    output = AggregateOutput(manifest, "daily-summary", {"answer": 1})
    client = FakeES()
    client.documents[("aggregates", output.aggregate_output_id)] = {
        "collection_id": "wrong", "manifest_fingerprint": "wrong", "output_key": "wrong"
    }
    with pytest.raises(ValueError, match="lineage conflict"):
        ElasticsearchAggregateSink(client, index="aggregates").upsert(output)
