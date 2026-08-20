"""Safe, allowlisted model metadata for Elasticsearch writeback."""

from __future__ import annotations

import ast
from collections.abc import Mapping
import re
from typing import Any


_SENSITIVE_KEY_PARTS = (
    "api_key", "apikey", "access_token", "auth_token", "authorization",
    "bearer", "client_secret", "password", "private_key", "secret",
)
_FORBIDDEN_METADATA_KEYS = {"model_spec", "base_url", "endpoint_url"}
_JWT_LIKE_RE = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_CREDENTIAL_TEXT_RE = re.compile(
    r"(?i)(?:\bbearer\s+|\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|"
    r"authorization|client[_-]?secret|password|private[_-]?key)\b\s*[:=])"
)
_SAFE_MODEL_FIELDS = {
    "model_name": ("model_name", "model"),
    "base_url_alias": ("base_url_alias", "endpoint_alias", "base_alias"),
    "num_ctx": ("num_ctx", "context_length"),
    "temperature": ("temperature",),
    "model_version": ("model_version", "version"),
}


def _looks_sensitive_key(key: Any) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    return (
        normalized in _FORBIDDEN_METADATA_KEYS
        or any(part in normalized for part in _SENSITIVE_KEY_PARTS)
    )


def _looks_sensitive_string(value: str) -> bool:
    return (
        _CREDENTIAL_TEXT_RE.search(value) is not None
        or _JWT_LIKE_RE.search(value) is not None
    )


def _mapping_from_value(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return None
    try:
        parsed = ast.literal_eval(stripped)
    except (SyntaxError, ValueError):
        return None
    return parsed if isinstance(parsed, Mapping) else None


def safe_model_metadata(model_spec: Any, **overrides: Any) -> dict[str, Any]:
    """Return only approved, non-secret model metadata fields.

    Endpoint URLs are intentionally not copied.  Operators may provide a
    non-sensitive ``base_url_alias`` / ``endpoint_alias`` instead.
    """
    source = _mapping_from_value(model_spec) or {}
    merged = dict(source)
    merged.update({key: value for key, value in overrides.items() if value is not None})
    safe: dict[str, Any] = {}
    for output_key, candidate_keys in _SAFE_MODEL_FIELDS.items():
        for candidate in candidate_keys:
            value = merged.get(candidate)
            if value is not None and value != "":
                safe[output_key] = value
                break
    return safe


def safe_model_tag(value: Any, *, fallback_spec: Any = None) -> str | None:
    """Return a non-sensitive model tag without serializing a full model spec."""
    mapped = _mapping_from_value(value)
    if mapped is not None:
        return safe_model_metadata(mapped).get("model_name")
    if value is not None:
        tag = str(value).strip()
        if tag and not _looks_sensitive_string(tag):
            return tag
    return safe_model_metadata(fallback_spec).get("model_name")


def strip_sensitive_metadata(value: Any) -> Any:
    """Recursively remove credential-like keys before metadata reaches ES."""
    if isinstance(value, Mapping):
        return {
            key: strip_sensitive_metadata(item)
            for key, item in value.items()
            if not _looks_sensitive_key(key)
        }
    if isinstance(value, list):
        return [strip_sensitive_metadata(item) for item in value]
    if isinstance(value, tuple):
        return [strip_sensitive_metadata(item) for item in value]
    if isinstance(value, str) and _looks_sensitive_string(value):
        return "[REDACTED]"
    return value
