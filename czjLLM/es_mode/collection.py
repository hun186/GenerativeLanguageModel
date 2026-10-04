"""Elasticsearch collection snapshot and aggregate upsert boundaries."""

from __future__ import annotations

import math
from typing import Any, Callable, Iterable, Mapping, Sequence

from czjLLM.es_mode.adapters.value_helpers import extract_by_path
from czjLLM.reduction import (
    AggregateOutput, CollectionManifest, LogicalWorkUnit, canonical_group_entries,
    deterministic_scalar_order_key, normalize_collection_window,
)
from czjLLM.reduction.artifacts import normalized_fingerprint


def _identity(value: Any, *, default_es_id: bool) -> str:
    if default_es_id:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Elasticsearch _id must be a non-empty string")
        return value
    if isinstance(value, bool):
        return f"bool:{str(value).lower()}"
    if isinstance(value, int):
        return f"int:{value}"
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Elasticsearch stable member identity must be finite")
        return f"float:{value.hex()}"
    if isinstance(value, str) and value:
        return f"str:{value}"
    raise ValueError(
        "Elasticsearch custom stable member identity must be a non-empty scalar"
    )


class ElasticsearchCollectionAdapter:
    """Compose an existing connected ElasticsearchAdapter and scan once."""

    def __init__(self, adapter: Any, *, source_alias: str, scan: Callable[..., Iterable[Mapping[str, Any]]] | None = None):
        self.adapter = adapter
        self.source_alias = source_alias
        self._scan = scan

    def snapshot(
        self, *, collection_id: str, index: str, query: Mapping[str, Any],
        identity_path: str = "_id", payload_paths: Sequence[str] = (),
        version_path: str | None = None, group_paths: Sequence[str] = (),
        processing_identity_path: str | None = None,
        order_paths: Sequence[str] = (), window: Mapping[str, Any] | None = None,
    ) -> tuple[CollectionManifest, ...]:
        if self.adapter.es is None:
            raise RuntimeError("Elasticsearch adapter must be connected")
        scan = self._scan
        if scan is None:
            from czjLLM.es_mode.adapters.elasticsearch_adapter import helpers
            scan = helpers.scan
        hits = list(scan(client=self.adapter.es, index=index, query=dict(query)))
        grouped: dict[
            tuple[Any, ...],
            list[tuple[tuple[tuple[int, Any], ...], LogicalWorkUnit]],
        ] = {}
        for hit in hits:
            source = hit.get("_source") or {}
            def get(path: str) -> Any:
                return hit.get(path) if path.startswith("_") else extract_by_path(source, path)
            logical_id = _identity(get(identity_path), default_es_id=identity_path == "_id")
            payload = {path: get(path) for path in payload_paths}
            provenance: dict[str, Any] = {"source_alias": self.source_alias}
            if version_path:
                provenance["source_version"] = get(version_path)
            elif hit.get("_seq_no") is not None and hit.get("_primary_term") is not None:
                provenance["source_version"] = {
                    "seq_no": hit["_seq_no"], "primary_term": hit["_primary_term"]
                }
            if processing_identity_path:
                provenance["processing_execution_fingerprint"] = get(processing_identity_path)
            unit = LogicalWorkUnit(logical_id, payload, provenance)
            group = tuple(get(path) for path in group_paths)
            if group_paths and any(value is None for value in group):
                raise ValueError("Elasticsearch group paths must not contain null")
            ordering = tuple(
                deterministic_scalar_order_key(get(path)) for path in order_paths
            ) + ((4, logical_id),)
            grouped.setdefault(group, []).append((ordering, unit))
        if not group_paths:
            grouped.setdefault((), [])
        result = []
        for values, entries in grouped.items():
            entries.sort(key=lambda item: item[0])
            group = canonical_group_entries(group_paths, values)
            provenance: dict[str, Any] = {"source_alias": self.source_alias}
            cid = collection_id
            if group_paths:
                provenance["group"] = group
                cid = f"{collection_id}:group:{normalized_fingerprint({'group': group})}"
            if window is not None:
                provenance["window"] = normalize_collection_window(window)
            result.append(CollectionManifest(cid, [entry[1] for entry in entries], provenance))
        return tuple(sorted(result, key=lambda item: item.collection_id))


class ElasticsearchAggregateSink:
    """Persist aggregate records with ES update/doc_as_upsert and deterministic _id."""

    def __init__(self, client: Any, *, index: str) -> None:
        self.client = client
        self.index = index

    def upsert(self, output: AggregateOutput) -> Any:
        document = output.to_mapping()
        return self.client.update(
            index=self.index,
            id=output.aggregate_output_id,
            body={
                "scripted_upsert": True,
                "script": {
                    "lang": "painless",
                    "source": (
                        "if (ctx.op == 'create') { "
                        "ctx._source.putAll(params.document); "
                        "} else { "
                        "if (!ctx._source.containsKey('aggregate_output_id') || "
                        "!ctx._source.containsKey('aggregate_output_contract_version') || "
                        "!ctx._source.containsKey('collection_id') || "
                        "!ctx._source.containsKey('manifest_fingerprint') || "
                        "!ctx._source.containsKey('output_key') || "
                        "ctx._source.aggregate_output_id != params.document.aggregate_output_id || "
                        "ctx._source.aggregate_output_contract_version != "
                        "params.document.aggregate_output_contract_version || "
                        "ctx._source.collection_id != params.document.collection_id || "
                        "ctx._source.manifest_fingerprint != params.document.manifest_fingerprint || "
                        "ctx._source.output_key != params.document.output_key) { "
                        "throw new IllegalArgumentException('aggregate lineage conflict'); } "
                        "ctx._source.putAll(params.document); }"
                    ),
                    "params": {
                        "document": document,
                    },
                },
                "upsert": {},
            },
        )
