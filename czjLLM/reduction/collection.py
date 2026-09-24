"""Immutable, source-independent collection identity contracts.

These contracts describe logical collection membership only.  They do not
query a source, execute reducers, or coordinate aggregate writeback.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence, Tuple

from .artifacts import normalized_fingerprint


COLLECTION_MANIFEST_CONTRACT_VERSION = "1"

_IDENTITY_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "access_token",
    "auth_token",
    "authorization",
    "bearer",
    "client_secret",
    "password",
    "private_key",
    "secret",
)
_FORBIDDEN_PROVENANCE_KEYS = {"model_spec", "base_url", "endpoint_url"}
_NONDETERMINISTIC_PROVENANCE_KEYS = {
    "created_at",
    "creation_time",
    "modified_at",
    "modification_time",
    "timestamp",
    "host",
    "hostname",
    "pid",
    "process_id",
    "thread_id",
    "session_id",
    "temporary_path",
    "temp_path",
    "tmp_path",
}
_CREDENTIAL_TEXT_RE = re.compile(
    r"(?i)(?:\bbearer\s+|\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|"
    r"authorization|client[_-]?secret|password|private[_-]?key)\b\s*[:=])"
)
_JWT_LIKE_RE = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_RAW_URL_RE = re.compile(r"(?i)^https?://")


class CollectionManifestError(ValueError):
    """Base class for malformed collection identity contracts."""


class CollectionManifestValidationError(CollectionManifestError):
    """A collection manifest or logical work unit failed strict validation."""


def _validate_identity(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise CollectionManifestValidationError(
            f"{field_name} must be a non-empty, surrounding-whitespace-free string"
        )
    if _IDENTITY_CONTROL_RE.search(value):
        raise CollectionManifestValidationError(
            f"{field_name} must not contain control characters"
        )
    if _RAW_URL_RE.match(value) or value.startswith(("/tmp/", "\\tmp\\")):
        raise CollectionManifestValidationError(
            f"{field_name} must be a logical identity, not a raw URL or temporary path"
        )
    return value


def _validate_provenance(value: Any, path: str = "provenance") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CollectionManifestValidationError(f"{path} keys must be strings")
            normalized = key.strip().lower().replace("-", "_")
            if normalized in _NONDETERMINISTIC_PROVENANCE_KEYS:
                raise CollectionManifestValidationError(
                    f"{path}.{key} is nondeterministic runtime state"
                )
            if normalized in _FORBIDDEN_PROVENANCE_KEYS or any(
                part in normalized for part in _SENSITIVE_KEY_PARTS
            ):
                raise CollectionManifestValidationError(
                    f"{path}.{key} is not permitted in provenance"
                )
            _validate_provenance(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_provenance(item, f"{path}[{index}]")
    elif isinstance(value, str) and (
        _CREDENTIAL_TEXT_RE.search(value)
        or _JWT_LIKE_RE.search(value)
        or _RAW_URL_RE.match(value.strip())
    ):
        raise CollectionManifestValidationError(
            f"{path} contains credential-like text or a raw endpoint URL"
        )


def _freeze_json(value: Any, path: str) -> Any:
    """Validate and recursively freeze an ordinary JSON-compatible value."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CollectionManifestValidationError(f"{path} must not contain NaN/Infinity")
        return value
    if isinstance(value, Mapping):
        frozen = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CollectionManifestValidationError(f"{path} keys must be strings")
            frozen[key] = _freeze_json(item, f"{path}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, f"{path}[{index}]") for index, item in enumerate(value))
    raise CollectionManifestValidationError(
        f"{path} must contain only JSON-compatible values, not {type(value).__name__}"
    )


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _require_exact_keys(value: Mapping[str, Any], expected: set, label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise CollectionManifestValidationError(
            f"{label} has invalid fields (missing={missing}, unknown={unknown})"
        )


@dataclass(frozen=True, init=False)
class LogicalWorkUnit:
    """One explicitly identified member in caller-supplied collection order.

    ``logical_id`` is supplied by the source adapter's stable semantics;
    ``payload`` is the reducer-facing JSON value and participates in identity;
    ``provenance`` is narrowly descriptive, non-secret metadata and also
    participates in identity.  Collection position is represented by the
    manifest's ordered ``units`` tuple rather than duplicated on each unit.
    """

    logical_id: str
    payload: Any
    provenance: Mapping[str, Any]

    def __init__(
        self,
        logical_id: str,
        payload: Any,
        provenance: Mapping[str, Any] | None = None,
    ) -> None:
        identity = _validate_identity(logical_id, "logical_id")
        provenance_value = {} if provenance is None else provenance
        if not isinstance(provenance_value, Mapping):
            raise CollectionManifestValidationError("provenance must be a mapping")
        _validate_provenance(provenance_value)
        object.__setattr__(self, "logical_id", identity)
        object.__setattr__(self, "payload", _freeze_json(payload, "payload"))
        object.__setattr__(self, "provenance", _freeze_json(provenance_value, "provenance"))

    def to_mapping(self) -> dict[str, Any]:
        """Return a detached, JSON-serializable canonical field mapping."""
        return {
            "logical_id": self.logical_id,
            "payload": _thaw_json(self.payload),
            "provenance": _thaw_json(self.provenance),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LogicalWorkUnit":
        if not isinstance(value, Mapping):
            raise CollectionManifestValidationError("logical work unit must be a mapping")
        _require_exact_keys(value, {"logical_id", "payload", "provenance"}, "logical work unit")
        return cls(
            logical_id=value["logical_id"],
            payload=value["payload"],
            provenance=value["provenance"],
        )


@dataclass(frozen=True, init=False)
class CollectionManifest:
    """Versioned immutable identity and provenance for an ordered collection."""

    contract_version: str
    collection_id: str
    units: Tuple[LogicalWorkUnit, ...]
    provenance: Mapping[str, Any]
    fingerprint: str

    def __init__(
        self,
        collection_id: str,
        units: Sequence[LogicalWorkUnit],
        provenance: Mapping[str, Any] | None = None,
        *,
        contract_version: str = COLLECTION_MANIFEST_CONTRACT_VERSION,
        fingerprint: str | None = None,
    ) -> None:
        if contract_version != COLLECTION_MANIFEST_CONTRACT_VERSION:
            raise CollectionManifestValidationError(
                f"unsupported collection manifest contract version: {contract_version!r}"
            )
        identity = _validate_identity(collection_id, "collection_id")
        if isinstance(units, (str, bytes)) or not isinstance(units, Sequence):
            raise CollectionManifestValidationError("units must be an ordered sequence")
        ordered_units = tuple(units)
        for unit in ordered_units:
            if not isinstance(unit, LogicalWorkUnit):
                raise CollectionManifestValidationError(
                    "units must contain only LogicalWorkUnit values"
                )
        seen = set()
        for unit in ordered_units:
            if unit.logical_id in seen:
                raise CollectionManifestValidationError(
                    f"duplicate logical work-unit identity: {unit.logical_id!r}"
                )
            seen.add(unit.logical_id)
        provenance_value = {} if provenance is None else provenance
        if not isinstance(provenance_value, Mapping):
            raise CollectionManifestValidationError("provenance must be a mapping")
        _validate_provenance(provenance_value)
        frozen_provenance = _freeze_json(provenance_value, "provenance")
        semantic = {
            "contract_version": contract_version,
            "collection_id": identity,
            "units": [unit.to_mapping() for unit in ordered_units],
            "provenance": _thaw_json(frozen_provenance),
        }
        computed = normalized_fingerprint(semantic)
        if fingerprint is not None and fingerprint != computed:
            raise CollectionManifestValidationError(
                "collection manifest fingerprint does not match semantic content"
            )
        object.__setattr__(self, "contract_version", contract_version)
        object.__setattr__(self, "collection_id", identity)
        object.__setattr__(self, "units", ordered_units)
        object.__setattr__(self, "provenance", frozen_provenance)
        object.__setattr__(self, "fingerprint", computed)

    def to_mapping(self) -> dict[str, Any]:
        """Return the canonical detached representation for JSON persistence."""
        return {
            "contract_version": self.contract_version,
            "collection_id": self.collection_id,
            "units": [unit.to_mapping() for unit in self.units],
            "provenance": _thaw_json(self.provenance),
            "fingerprint": self.fingerprint,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CollectionManifest":
        """Strictly reconstruct a manifest and verify its persisted fingerprint."""
        if not isinstance(value, Mapping):
            raise CollectionManifestValidationError("collection manifest must be a mapping")
        _require_exact_keys(
            value,
            {"contract_version", "collection_id", "units", "provenance", "fingerprint"},
            "collection manifest",
        )
        raw_units = value["units"]
        if not isinstance(raw_units, list):
            raise CollectionManifestValidationError("serialized units must be a list")
        return cls(
            collection_id=value["collection_id"],
            units=tuple(LogicalWorkUnit.from_mapping(unit) for unit in raw_units),
            provenance=value["provenance"],
            contract_version=value["contract_version"],
            fingerprint=value["fingerprint"],
        )
