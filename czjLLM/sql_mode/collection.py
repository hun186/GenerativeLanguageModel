"""Explicit SQL collection snapshot and aggregate persistence boundaries."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from czjLLM.reduction import (
    AggregateOutput, CollectionManifest, LogicalWorkUnit, normalize_collection_window,
)
from czjLLM.reduction.artifacts import normalized_fingerprint


def _stable_scalar(value: Any, label: str) -> str:
    if value is None or value == "":
        raise ValueError(f"{label} must not be NULL or empty")
    if isinstance(value, bool):
        return f"bool:{str(value).lower()}"
    if isinstance(value, int):
        return f"int:{value}"
    if isinstance(value, float):
        return f"float:{value.hex()}"
    if isinstance(value, str):
        return f"str:{value}"
    if isinstance(value, bytes):
        return f"bytes:{value.hex()}"
    raise ValueError(f"{label} must be a stable SQL scalar")


def _group_collection_id(base: str, group: Mapping[str, Any]) -> str:
    return f"{base}:group:{normalized_fingerprint({'group': dict(group)})}"


@dataclass(frozen=True)
class SQLCollectionQuery:
    sql: str
    parameters: Sequence[Any]
    member_id_field: str
    payload_fields: Sequence[str]
    version_field: str | None = None
    group_fields: Sequence[str] = ()
    order_fields: Sequence[str] = ()


class SQLCollectionAdapter:
    """Snapshot one parameterized query from an already-connected DB adapter."""

    def __init__(self, adapter: Any, *, source_alias: str) -> None:
        if not source_alias or not source_alias.strip():
            raise ValueError("source_alias is required")
        self.adapter = adapter
        self.source_alias = source_alias

    def snapshot(
        self,
        *,
        collection_id: str,
        query: SQLCollectionQuery,
        window: Mapping[str, Any] | None = None,
    ) -> tuple[CollectionManifest, ...]:
        if self.adapter.conn is None:
            raise RuntimeError("SQL adapter must be connected")
        cursor = self.adapter.conn.cursor()
        try:
            cursor.execute(query.sql, tuple(query.parameters))
            names = [item[0] for item in cursor.description]
            rows = [dict(zip(names, row)) for row in cursor.fetchall()]
        finally:
            cursor.close()

        required = set(query.payload_fields) | set(query.group_fields) | set(query.order_fields)
        required.add(query.member_id_field)
        if query.version_field:
            required.add(query.version_field)
        missing = required - set(names)
        if missing:
            raise ValueError(f"SQL collection query did not select fields: {sorted(missing)}")
        groups: dict[tuple[Any, ...], list[tuple[tuple[Any, ...], LogicalWorkUnit]]] = {}
        for row in rows:
            logical_id = _stable_scalar(row[query.member_id_field], "SQL stable member ID")
            payload = {field: row[field] for field in query.payload_fields}
            provenance: dict[str, Any] = {"source_alias": self.source_alias}
            if query.version_field:
                provenance["source_version"] = row[query.version_field]
            unit = LogicalWorkUnit(logical_id, payload, provenance)
            group_key = tuple(row[field] for field in query.group_fields)
            if query.group_fields and any(value is None for value in group_key):
                raise ValueError("SQL group fields must not contain NULL")
            order = tuple(row[field] for field in query.order_fields) + (logical_id,)
            groups.setdefault(group_key, []).append((order, unit))
        if not query.group_fields:
            groups.setdefault((), [])

        manifests = []
        for group_key, entries in groups.items():
            entries.sort(key=lambda item: tuple(_stable_scalar(v, "order value") for v in item[0]))
            group = dict(zip(query.group_fields, group_key))
            provenance: dict[str, Any] = {"source_alias": self.source_alias}
            current_id = collection_id
            if group:
                provenance["group"] = group
                current_id = _group_collection_id(collection_id, group)
            if window is not None:
                provenance["window"] = normalize_collection_window(window)
            manifests.append(CollectionManifest(current_id, [item[1] for item in entries], provenance))
        return tuple(sorted(manifests, key=lambda item: item.collection_id))


class SQLiteAggregateSink:
    """Dedicated SQLite aggregate table with PK-backed atomic upsert."""

    def __init__(self, connection: sqlite3.Connection, *, table: str = "collection_aggregates"):
        if not table.replace("_", "").isalnum():
            raise ValueError("table must be a simple SQL identifier")
        self.connection = connection
        self.table = table

    def ensure_schema(self) -> None:
        self.connection.execute(f'''CREATE TABLE IF NOT EXISTS "{self.table}" (
            aggregate_output_id TEXT PRIMARY KEY,
            contract_version TEXT NOT NULL,
            collection_id TEXT NOT NULL,
            manifest_fingerprint TEXT NOT NULL,
            output_key TEXT NOT NULL,
            payload TEXT NOT NULL,
            provenance TEXT NOT NULL
        )''')
        self.connection.commit()

    def upsert(self, output: AggregateOutput) -> None:
        value = output.to_mapping()
        row = (
            value["aggregate_output_id"], value["aggregate_output_contract_version"],
            value["collection_id"], value["manifest_fingerprint"], value["output_key"],
            json.dumps(value["payload"], ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            json.dumps(value["provenance"], ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self.connection.execute(
                f'SELECT collection_id, manifest_fingerprint, output_key FROM "{self.table}" WHERE aggregate_output_id=?',
                (output.aggregate_output_id,),
            ).fetchone()
            lineage = row[2:5]
            if existing is not None and tuple(existing) != lineage:
                raise ValueError("aggregate_output_id conflicts with persisted lineage")
            self.connection.execute(f'''INSERT INTO "{self.table}"
                (aggregate_output_id, contract_version, collection_id, manifest_fingerprint, output_key, payload, provenance)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(aggregate_output_id) DO UPDATE SET
                    payload=excluded.payload, provenance=excluded.provenance''', row)
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
