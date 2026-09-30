"""Offline production-boundary coverage for Reduction Engine PR G."""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import pytest

from czjLLM.es_mode.collection import ElasticsearchAggregateSink, ElasticsearchCollectionAdapter
from czjLLM.reduction import (
    AggregateOutput, CollectionManifest, CollectionManifestStore, LogicalWorkUnit,
    parse_reduction_config, reduce_single_pass,
)
from czjLLM.sql_mode.adapters.sqlite_adapter import SQLiteAdapter
from czjLLM.sql_mode.collection import SQLCollectionAdapter, SQLCollectionQuery, SQLiteAggregateSink


pytestmark = pytest.mark.e2e


class AggregateTransport:
    """Deterministic double for only the external ES update transport."""

    def __init__(self):
        self.documents = {}

    def update(self, *, index, id, body):
        assert "ctx.op == 'create'" in body["script"]["source"]
        params = body["script"]["params"]
        existing = self.documents.get((index, id))
        incoming = params["document"]
        lineage = (
            "aggregate_output_id", "aggregate_output_contract_version",
            "collection_id", "manifest_fingerprint", "output_key",
        )
        if existing is not None:
            if any(field not in existing or existing[field] != incoming[field] for field in lineage):
                raise ValueError("aggregate lineage conflict")
        self.documents[(index, id)] = incoming
        return {"result": "updated", "_id": id}


def test_sql_collection_snapshot_persist_and_idempotent_aggregate(tmp_path):
    database = tmp_path / "collection.sqlite"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE source (id INTEGER PRIMARY KEY, body TEXT, rank INTEGER)")
    connection.executemany("INSERT INTO source VALUES (?, ?, ?)", [(1, "ten", 10), (2, "two", 2)])
    connection.commit(); connection.close()

    adapter = SQLiteAdapter({"server": str(database)}).connect()
    source = SQLCollectionAdapter(adapter, source_alias="offline-sql")
    query = SQLCollectionQuery(
        "SELECT id, body, rank FROM source", (), "id", ("body", "rank"), order_fields=("rank",)
    )
    manifest = source.snapshot(collection_id="offline-reports", query=query)[0]
    saved = tmp_path / "manifest.json"
    CollectionManifestStore.save(saved, manifest)
    adapter.conn.execute("INSERT INTO source VALUES (3, 'new', 3)"); adapter.conn.commit()
    assert CollectionManifestStore.load(saved).to_mapping() == manifest.to_mapping()
    assert len(source.snapshot(collection_id="offline-reports", query=query)[0].units) == 3

    output = AggregateOutput(manifest, "daily-summary", {"members": 2})
    sink = SQLiteAggregateSink(adapter.conn); sink.ensure_schema()
    sink.upsert(output); sink.upsert(output)
    row = adapter.conn.execute(
        "SELECT aggregate_output_id, manifest_fingerprint, payload FROM collection_aggregates"
    ).fetchall()
    assert row == [(output.aggregate_output_id, manifest.fingerprint, json.dumps({"members": 2}, separators=(",", ":")))]
    adapter.close()


def test_es_collection_snapshot_atomic_aggregate_retry_and_conflict():
    hits = [
        {"_id": "ten", "_source": {"body": "ten", "rank": 10}},
        {"_id": "two", "_source": {"body": "two", "rank": 2}},
    ]
    transport = AggregateTransport()
    adapter = SimpleNamespace(es=transport)
    source = ElasticsearchCollectionAdapter(
        adapter,
        source_alias="offline-es",
        scan=lambda **_: iter(hits),
    )
    manifest = source.snapshot(
        collection_id="offline-docs", index="source", query={"query": {"match_all": {}}},
        payload_paths=("body", "rank"), order_paths=("rank",),
    )[0]
    output = AggregateOutput(manifest, "daily-summary", {"members": 2})
    sink = ElasticsearchAggregateSink(transport, index="aggregates")
    sink.upsert(output); sink.upsert(output)
    assert list(transport.documents) == [("aggregates", output.aggregate_output_id)]
    assert transport.documents[("aggregates", output.aggregate_output_id)] == output.to_mapping()

    incomplete = output.to_mapping()
    incomplete.pop("aggregate_output_id")
    transport.documents[("aggregates", output.aggregate_output_id)] = incomplete
    with pytest.raises(ValueError, match="lineage conflict"):
        sink.upsert(output)
    assert transport.documents[("aggregates", output.aggregate_output_id)] == incomplete

    incompatible = output.to_mapping()
    incompatible["aggregate_output_contract_version"] = "incompatible"
    transport.documents[("aggregates", output.aggregate_output_id)] = incompatible
    with pytest.raises(ValueError, match="lineage conflict"):
        sink.upsert(output)


def test_deterministic_composite_manifest_to_idempotent_sqlite_aggregate(tmp_path):
    manifest = CollectionManifest("ranked-entities", (
        LogicalWorkUnit("a-first", {"id": "a", "score": 2}),
        LogicalWorkUnit("a-duplicate", {"id": "a", "score": 99}),
        LogicalWorkUnit("b", {"id": "b", "score": 10}),
        LogicalWorkUnit("c", {"id": "c", "score": 10}),
    ))
    config = parse_reduction_config({"enabled": True, "profile": "composite", "options": {"steps": [
        {"profile": "dedup", "options": {"key_paths": ["id"]}},
        {"profile": "rank", "options": {"score_path": "score"}},
        {"profile": "top_k", "options": {"k": 2}},
    ]}})
    payloads = [unit.to_mapping()["payload"] for unit in manifest.units]
    first = reduce_single_pass(payloads, config); retry = reduce_single_pass(payloads, config)
    assert first.payload == retry.payload == [{"id": "b", "score": 10}, {"id": "c", "score": 10}]

    connection = sqlite3.connect(tmp_path / "composite.sqlite")
    sink = SQLiteAggregateSink(connection); sink.ensure_schema()
    output = AggregateOutput(manifest, "top-two", first.payload)
    sink.upsert(output); sink.upsert(AggregateOutput(manifest, "top-two", retry.payload))
    assert connection.execute("SELECT COUNT(*) FROM collection_aggregates").fetchone() == (1,)
    connection.close()
