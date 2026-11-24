"""Explicit read-only ES source observation for future quality retry integration.

No caller may treat this as authenticated identity or a dispatch claim.
Only same-concrete-index, scalar string keys are supported for now.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from collections.abc import Mapping

from .adapters.value_helpers import extract_by_path

_INDEX = re.compile(r"[a-z0-9_][a-z0-9_.-]{0,254}\Z")
_FIELD = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,95}\Z")


class SourceObservationUnavailable(ValueError):
    """Fixed message; never expose source keys or raw ES errors."""


@dataclass(frozen=True)
class SourceObservation:
    cluster_uuid: str = field(repr=False)
    index_uuid: str = field(repr=False)
    concrete_index: str = field(repr=False)
    document_id: str = field(repr=False)

    def scoped_document_id(self) -> str:
        # Unambiguous private identity; the future ledger must HMAC this
        # value. No raw identifier is written to disk or logs here.
        value = json.dumps(
            ["es-source-v1", self.cluster_uuid, self.index_uuid,
             self.concrete_index, self.document_id],
            ensure_ascii=True, separators=(",", ":"),
        )
        if len(value) > 4096:
            raise SourceObservationUnavailable("source identity too large")
        return value


def _require(ok):
    if not ok:
        raise SourceObservationUnavailable("source observation unavailable")


def _token(value, limit=512):
    return (type(value) is str and 0 < len(value) <= limit
            and bool(value.strip()) and value != "_na_"
            and not any(ord(c) < 32 for c in value))


def _namespace(es, index, timeout):
    info = es.info(request_timeout=timeout)
    cluster_uuid = info.get("cluster_uuid")
    _require(_token(cluster_uuid, 128))
    settings = es.indices.get_settings(index=index, request_timeout=timeout)
    _require(isinstance(settings, Mapping) and set(settings) == {index})
    index_uuid = settings[index]["settings"]["index"]["uuid"]
    _require(_token(index_uuid, 128))
    return cluster_uuid, index_uuid


def observe_source(es, cfg, logical_id: str) -> SourceObservation:
    """Read current unique source hit using the configured exact key.

    This deliberately does not use the legacy writeback fallback to a business
    key, normalize arrays, follow aliases, or change existing scan semantics.
    A before/after namespace check is not a transaction or TLS attestation.
    """
    try:
        _require(es is not None and isinstance(cfg, Mapping))
        index = cfg.get("src_index")
        _require(type(index) is str and _INDEX.fullmatch(index)
                 and cfg.get("tgt_index") == index)
        pk = cfg.get("id_col")
        _require(type(pk) is str and _FIELD.fullmatch(pk))
        _require(_token(logical_id))
        timeout = int(cfg.get("es_request_timeout", 60))
        _require(1 <= timeout <= 600)
        before = _namespace(es, index, timeout)
        if pk == "_id":
            query = {"ids": {"values": [logical_id]}}
            source_fields = False
        else:
            suffix = cfg.get("pk_keyword_suffix", ".keyword")
            _require(type(suffix) is str and suffix in ("", ".keyword"))
            query = {"term": {pk + suffix: logical_id}}
            source_fields = [pk]
        response = es.search(
            index=index, request_timeout=timeout,
            body={"query": query, "_source": source_fields,
                  "size": 2, "track_total_hits": True},
        )
        _require(response.get("timed_out") is False
                 and response.get("terminated_early", False) is False)
        shards = response["_shards"]
        _require(type(shards.get("total")) is int and shards["total"] > 0
                 and type(shards.get("successful")) is int
                 and shards["successful"] == shards["total"]
                 and type(shards.get("failed")) is int and shards["failed"] == 0)
        hits = response["hits"]
        total = hits["total"]
        _require(isinstance(total, Mapping) and total.get("relation") == "eq"
                 and type(total.get("value")) is int and total["value"] == 1
                 and isinstance(hits["hits"], list) and len(hits["hits"]) == 1)
        hit = hits["hits"][0]
        doc_id = hit.get("_id")
        _require(hit.get("_index") == index and _token(doc_id))
        if pk == "_id":
            _require(doc_id == logical_id)
        else:
            observed = extract_by_path(hit.get("_source"), pk)
            _require(type(observed) is str and observed == logical_id)
        _require(_namespace(es, index, timeout) == before)
        result = SourceObservation(*before, index, doc_id)
        result.scoped_document_id()  # Enforce bound before exposing observation.
        return result
    except SourceObservationUnavailable:
        raise
    except Exception:
        raise SourceObservationUnavailable("source observation unavailable") from None
