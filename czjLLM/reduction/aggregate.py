"""Source-independent aggregate output identity and manifest persistence."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from czjLLM.utilities.atomic_io import atomic_write_json

from .artifacts import normalized_fingerprint
from .collection import (
    CollectionManifest,
    CollectionManifestValidationError,
    _freeze_json,
    _thaw_json,
    _validate_identity,
    _validate_provenance,
)


AGGREGATE_OUTPUT_CONTRACT_VERSION = "1"


def deterministic_scalar_order_key(value: Any) -> tuple[int, Any]:
    """Return a total, semantic key for supported JSON/SQL scalar values.

    Booleans, numbers, strings, and bytes occupy distinct deterministic type
    domains. Integers and finite floats share the numeric domain so their
    natural numeric order is retained. Null and structured values are not
    meaningful explicit order values and therefore fail rather than falling
    back to representation ordering.
    """
    if isinstance(value, bool):
        return (0, int(value))
    if isinstance(value, int):
        return (1, value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("order values must not contain NaN or Infinity")
        return (1, value)
    if isinstance(value, str):
        return (2, value)
    if isinstance(value, bytes):
        return (3, value)
    raise ValueError(f"unsupported non-scalar order value: {type(value).__name__}")


def canonical_group_entries(
    fields: Sequence[str], values: Sequence[Any],
) -> list[dict[str, Any]]:
    """Represent ordered source field/value pairs without dynamic provenance keys."""
    return [
        {"field": field, "value": value}
        for field, value in zip(fields, values)
    ]


def normalize_collection_window(window: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize semantic half-open ``[start, end)`` metadata."""
    required = {"field", "start", "end", "timezone"}
    if not required.issubset(window) or window["start"] >= window["end"]:
        raise ValueError("window requires field/start/end/timezone and start < end")
    result = {key: window[key] for key in ("field", "start", "end", "timezone")}
    if "cutoff_policy" in window:
        result["cutoff_policy"] = window["cutoff_policy"]
    result["bounds"] = "[start,end)"
    return result


def _aggregate_id_from_fields(
    collection_id: str, manifest_fingerprint: str, output_key: str,
) -> str:
    """Use the one canonical v1 aggregate identity algorithm everywhere."""
    return "aggregate-v1-" + normalized_fingerprint(
        {
            "aggregate_output_contract_version": AGGREGATE_OUTPUT_CONTRACT_VERSION,
            "collection_id": collection_id,
            "manifest_fingerprint": manifest_fingerprint,
            "output_key": output_key,
        }
    )


def derive_aggregate_output_id(manifest: CollectionManifest, output_key: str) -> str:
    """Return a portable deterministic ID for one logical manifest product."""
    key = _validate_identity(output_key, "output_key")
    return _aggregate_id_from_fields(manifest.collection_id, manifest.fingerprint, key)


_AGGREGATE_LINEAGE_FIELDS = (
    "aggregate_output_contract_version", "aggregate_output_id",
    "collection_id", "manifest_fingerprint", "output_key",
)


def extract_aggregate_lineage(value: AggregateOutput | Mapping[str, Any]) -> dict[str, str]:
    """Read validated identity fields from a v1 aggregate or persisted mapping.

    The canonical AggregateOutput mapping remains the only payload contract.
    No payload, provenance, storage, or traversal is duplicated here. Without
    the original CollectionManifest this checks internal ID consistency, not
    that the manifest's contents exist or match its fingerprint.
    """
    record = value.to_mapping() if isinstance(value, AggregateOutput) else value
    if not isinstance(record, Mapping):
        raise CollectionManifestValidationError("aggregate lineage must be a mapping")
    missing = set(_AGGREGATE_LINEAGE_FIELDS) - set(record)
    if missing:
        raise CollectionManifestValidationError(
            f"aggregate lineage is missing required fields: {sorted(missing)}"
        )
    if record["aggregate_output_contract_version"] != AGGREGATE_OUTPUT_CONTRACT_VERSION:
        raise CollectionManifestValidationError(
            "unsupported aggregate output contract version"
        )
    collection_id = _validate_identity(record["collection_id"], "collection_id")
    output_key = _validate_identity(record["output_key"], "output_key")
    fingerprint = record["manifest_fingerprint"]
    if not isinstance(fingerprint, str) or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None:
        raise CollectionManifestValidationError(
            "manifest_fingerprint must be a lowercase SHA-256 fingerprint"
        )
    aggregate_id = _validate_identity(record["aggregate_output_id"], "aggregate_output_id")
    if aggregate_id != _aggregate_id_from_fields(collection_id, fingerprint, output_key):
        raise CollectionManifestValidationError(
            "aggregate_output_id does not match aggregate lineage"
        )
    return {field: record[field] for field in _AGGREGATE_LINEAGE_FIELDS}


def same_aggregate_lineage(
    left: AggregateOutput | Mapping[str, Any],
    right: AggregateOutput | Mapping[str, Any],
) -> bool:
    """Compare validated aggregate identity, not output payload or freshness."""
    return extract_aggregate_lineage(left) == extract_aggregate_lineage(right)


@dataclass(frozen=True, init=False)
class AggregateOutput:
    """A final, already-validated aggregate payload plus immutable lineage."""

    aggregate_output_id: str
    collection_id: str
    manifest_fingerprint: str
    output_key: str
    payload: Any
    provenance: Mapping[str, Any]
    contract_version: str

    def __init__(
        self,
        manifest: CollectionManifest,
        output_key: str,
        payload: Any,
        provenance: Mapping[str, Any] | None = None,
    ) -> None:
        key = _validate_identity(output_key, "output_key")
        provenance_value = {} if provenance is None else provenance
        _validate_provenance(provenance_value)
        object.__setattr__(self, "aggregate_output_id", derive_aggregate_output_id(manifest, key))
        object.__setattr__(self, "collection_id", manifest.collection_id)
        object.__setattr__(self, "manifest_fingerprint", manifest.fingerprint)
        object.__setattr__(self, "output_key", key)
        object.__setattr__(self, "payload", _freeze_json(payload, "payload"))
        object.__setattr__(self, "provenance", _freeze_json(provenance_value, "provenance"))
        object.__setattr__(self, "contract_version", AGGREGATE_OUTPUT_CONTRACT_VERSION)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "aggregate_output_contract_version": self.contract_version,
            "aggregate_output_id": self.aggregate_output_id,
            "collection_id": self.collection_id,
            "manifest_fingerprint": self.manifest_fingerprint,
            "output_key": self.output_key,
            "payload": _thaw_json(self.payload),
            "provenance": _thaw_json(self.provenance),
        }

    def as_logical_work_unit_payload(self) -> dict[str, Any]:
        """Return complete lineage for a later aggregate-of-aggregates member."""
        return self.to_mapping()

    def lineage_mapping(self) -> dict[str, str]:
        """Return a validated payload-free projection of canonical v1 lineage."""
        return extract_aggregate_lineage(self)


class CollectionManifestStore:
    """Atomic file persistence; loading is strict and never queries a source."""

    @staticmethod
    def save(path: str | Path, manifest: CollectionManifest) -> None:
        atomic_write_json(str(path), manifest.to_mapping())

    @staticmethod
    def load(path: str | Path) -> CollectionManifest:
        try:
            with Path(path).open("r", encoding="utf-8") as stream:
                value = json.load(stream)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CollectionManifestValidationError(
                f"cannot load collection manifest {path}: {exc}"
            ) from exc
        return CollectionManifest.from_mapping(value)
