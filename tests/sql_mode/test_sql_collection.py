import json
import sqlite3

import pytest

from czjLLM.reduction import AggregateOutput, CollectionManifestStore
from czjLLM.sql_mode.adapters import SQLiteAdapter
from czjLLM.sql_mode.collection import SQLCollectionAdapter, SQLCollectionQuery, SQLiteAggregateSink


def setup_db(path):
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE source (id INTEGER, text TEXT, revision INTEGER, day TEXT, rank INTEGER)")
    connection.executemany("INSERT INTO source VALUES (?, ?, ?, ?, ?)", [(2, "b", 4, "2026-09-24", 1), (1, "a", 3, "2026-09-24", 1), (3, "c", 5, "2026-09-25", 1)])
    connection.commit(); connection.close()


def query(sql="SELECT id, text, revision, day, rank FROM source WHERE day >= ?"):
    return SQLCollectionQuery(sql, ("2026-09-24",), "id", ("text",), "revision", (), ("rank",))


def test_sql_snapshot_bound_parameters_order_payload_version_and_retry(tmp_path):
    path = tmp_path / "db.sqlite"; setup_db(path)
    adapter = SQLiteAdapter({"server": str(path)}).connect()
    collection = SQLCollectionAdapter(adapter, source_alias="reporting")
    first = collection.snapshot(collection_id="reports", query=query())[0]
    assert [u.logical_id for u in first.units] == ["int:1", "int:2", "int:3"]
    assert first.units[0].payload["text"] == "a"
    assert first.units[0].provenance["source_version"] == 3
    assert "server" not in json.dumps(first.to_mapping())
    saved = tmp_path / "manifest.json"; CollectionManifestStore.save(saved, first)
    adapter.conn.execute("INSERT INTO source VALUES (4, 'd', 1, '2026-09-26', 1)"); adapter.conn.commit()
    assert len(first.units) == len(CollectionManifestStore.load(saved).units) == 3
    second = collection.snapshot(collection_id="reports", query=query())[0]
    assert len(second.units) == 4 and second.fingerprint != first.fingerprint
    adapter.close()


def test_sql_incidental_order_grouping_duplicates_and_changed_payload(tmp_path):
    path = tmp_path / "db.sqlite"; setup_db(path)
    adapter = SQLiteAdapter({"server": str(path)}).connect(); source = SQLCollectionAdapter(adapter, source_alias="safe")
    asc = source.snapshot(collection_id="all", query=query("SELECT id,text,revision,day,rank FROM source WHERE day >= ? ORDER BY id"))[0]
    desc = source.snapshot(collection_id="all", query=query("SELECT id,text,revision,day,rank FROM source WHERE day >= ? ORDER BY id DESC"))[0]
    assert asc.fingerprint == desc.fingerprint
    grouped_query = SQLCollectionQuery("SELECT id,text,revision,day,rank FROM source", (), "id", ("text",), group_fields=("day",))
    grouped = source.snapshot(collection_id="daily", query=grouped_query)
    assert len(grouped) == 2 and all(m.provenance["group"] for m in grouped)
    adapter.conn.execute("UPDATE source SET text='different' WHERE id=1"); adapter.conn.commit()
    assert source.snapshot(collection_id="all", query=query())[0].fingerprint != asc.fingerprint
    adapter.conn.execute("INSERT INTO source VALUES (1,'duplicate',9,'2026-09-25',1)"); adapter.conn.commit()
    with pytest.raises(ValueError, match="duplicate"):
        source.snapshot(collection_id="all", query=query())
    adapter.close()


def test_sql_parameter_is_bound_not_interpolated(tmp_path):
    path = tmp_path / "db.sqlite"; setup_db(path)
    adapter = SQLiteAdapter({"server": str(path)}).connect(); source = SQLCollectionAdapter(adapter, source_alias="safe")
    hostile = "2026-09-24' OR 1=1 --"
    q = SQLCollectionQuery("SELECT id,text FROM source WHERE day = ?", (hostile,), "id", ("text",))
    assert source.snapshot(collection_id="bound", query=q)[0].units == ()
    adapter.close()


def test_sql_aggregate_upsert_is_idempotent_after_lost_ack(tmp_path):
    path = tmp_path / "db.sqlite"; setup_db(path)
    adapter = SQLiteAdapter({"server": str(path)}).connect()
    manifest = SQLCollectionAdapter(adapter, source_alias="safe").snapshot(collection_id="all", query=query())[0]
    output = AggregateOutput(manifest, "daily-summary", {"result": "final"}, {"profile": "validated"})
    sink = SQLiteAggregateSink(adapter.conn); sink.ensure_schema(); sink.upsert(output)
    sink.upsert(output)  # committed, acknowledgement treated as lost, same operation retried
    row = adapter.conn.execute("SELECT COUNT(*), collection_id, manifest_fingerprint, output_key, payload FROM collection_aggregates").fetchone()
    assert row[:4] == (1, "all", manifest.fingerprint, "daily-summary")
    assert json.loads(row[4]) == {"result": "final"}
    other = AggregateOutput(manifest, "daily-topics", {"topics": []}); sink.upsert(other)
    assert adapter.conn.execute("SELECT COUNT(*) FROM collection_aggregates").fetchone()[0] == 2
    adapter.close()
