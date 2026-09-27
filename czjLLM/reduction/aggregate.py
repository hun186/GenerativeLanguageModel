"""Source-independent aggregate output identity and manifest persistence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

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


def derive_aggregate_output_id(manifest: CollectionManifest, output_key: str) -> str:
    """Return a portable deterministic ID for one logical manifest product."""
    key = _validate_identity(output_key, "output_key")
    return "aggregate-v1-" + normalized_fingerprint(
        {
            "aggregate_output_contract_version": AGGREGATE_OUTPUT_CONTRACT_VERSION,
            "collection_id": manifest.collection_id,
            "manifest_fingerprint": manifest.fingerprint,
            "output_key": key,
        }
    )


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
