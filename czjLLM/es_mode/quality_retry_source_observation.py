"""Explicit read-only ES source observation for future quality retry integration.

No caller may treat this as authenticated identity or a dispatch claim.
Only same-concrete-index, scalar string keys are supported for now.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
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


@dataclass(frozen=True)
class SourceInputObservation:
    source: SourceObservation = field(repr=False)
    input_sha256: str = field(repr=False)

    def scoped_document_revision(self) -> str:
        """Private revision identity, to be HMACed by the future ledger."""
        value = json.dumps(
            ["es-source-input-v1", self.source.scoped_document_id(), self.input_sha256],
            ensure_ascii=True, separators=(",", ":"),
        )
        _require(len(value) <= 4096)
        return value


def _overlaps(a, b):
    return a == b or a.startswith(b + ".") or b.startswith(a + ".")


def _input_snapshot(cfg, expected_input, expected_stage_inputs):
    # Start with a deliberately narrow same-index, single-output contract.
    # Do not silently hash generated outputs, their metadata or time fields.
    primary = cfg.get("input_col")
    # Match the pending adapter's output_cols precedence, but refuse
    # malformed values or disagreement with the legacy primary sink field.
    # A narrow observer must not assume the second configured output is input.
    def single_output(raw):
        if type(raw) in (list, tuple):
            _require(len(raw) == 1)
            raw = raw[0]
        _require(type(raw) is str and _FIELD.fullmatch(raw))
        return raw

    legacy = cfg.get("output_col")
    explicit = cfg.get("output_cols")
    output = single_output(explicit if explicit is not None else legacy)
    if legacy is not None:
        _require(single_output(legacy) == output)
    _require(type(primary) is str and _FIELD.fullmatch(primary))
    _require(not cfg.get("es_writeback_rules") and not cfg.get("stage_output_cols"))
    raw_stages = cfg.get("stage_source_input_cols") or []
    _require(type(raw_stages) is list and len(raw_stages) <= 64)
    _require(all(type(p) is str and _FIELD.fullmatch(p) for p in raw_stages))
    stages = sorted(set(p for p in raw_stages if p != primary))
    _require(type(expected_stage_inputs) is dict
             and set(expected_stage_inputs) == set(stages))
    rr = cfg.get("rerun") or {}
    meta = rr.get("meta_field") or output + "_meta"
    _require(type(meta) is str and _FIELD.fullmatch(meta))
    excluded = (output, meta, "update_time_ai", "_id")
    fields = [primary] + stages
    _require(not any(_overlaps(p, q) for p in fields for q in excluded))
    _require(not any(_overlaps(p, q) for i, p in enumerate(fields) for q in fields[i+1:]))
    pairs = [(primary, expected_input)] + [(p, expected_stage_inputs[p]) for p in stages]
    _require(all(type(v) is str and bool(v.strip()) for _, v in pairs))
    _require(sum(len(v) for _, v in pairs) <= 4_000_000)
    return tuple(pairs)


def observe_source_inputs(es, cfg, logical_id, *, expected_input, expected_stage_inputs):
    """Compare exact caller-supplied input snapshot with a unique ES hit.

    The caller still must establish actual queued/consumed input provenance.
    This is not an atomic source revision, provider receipt or authorization.
    """
    try:
        pairs = _input_snapshot(cfg, expected_input, expected_stage_inputs)
        return observe_source(es, cfg, logical_id, _input_pairs=pairs)
    except SourceObservationUnavailable:
        raise
    except Exception:
        raise SourceObservationUnavailable("source observation unavailable") from None


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


def observe_source(es, cfg, logical_id: str, *, _input_pairs=None):
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
        if _input_pairs is not None:
            source_fields = list(dict.fromkeys((source_fields or []) + [p for p, _ in _input_pairs]))
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
        if _input_pairs is None:
            return result
        for path, expected in _input_pairs:
            actual = extract_by_path(hit.get("_source"), path)
            _require(type(actual) is str and actual == expected)
        encoded = json.dumps(["es-input-v1", _input_pairs], ensure_ascii=True,
                             separators=(",", ":")).encode("ascii")
        observation = SourceInputObservation(result, hashlib.sha256(encoded).hexdigest())
        observation.scoped_document_revision()
        return observation
    except SourceObservationUnavailable:
        raise
    except Exception:
        raise SourceObservationUnavailable("source observation unavailable") from None
