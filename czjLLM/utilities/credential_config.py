"""Secret-safe display and validation for SQL/ES connection configurations.

Production credentials belong in runtime environment or private files, never
in a tracked Python/YAML example. Never log raw config mappings.
"""
from __future__ import annotations

import os
import re
from collections.abc import Mapping

_SECRET_FIELD = re.compile(
    r"(?:pass(?:word|phrase)?|pwd|secret|token|api[_-]?key|"
    r"auth(?:orization)?|credential|cookie|private[_-]?key|"
    r"reset_confirm_code)",
    re.IGNORECASE,
)
REDACTED = "[REDACTED]"


def redact_config(value, *, _sensitive=False):
    """Return a log-safe detached view, including nested credentials."""
    if _sensitive:
        return REDACTED
    if isinstance(value, Mapping):
        return {key: redact_config(v, _sensitive=bool(_SECRET_FIELD.search(str(key))))
                for key, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact_config(v) for v in value]
    # Avoid custom object's repr(), which could contain secret-bearing fields.
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return "<object>"


def validate_es_config(config):
    """Reject partial ES username/password pairs before a connection is tried."""
    if not isinstance(config, Mapping):
        raise ValueError("ES configuration must be a mapping")
    user = str(config.get("es_user") or "").strip()
    password = config.get("es_pass")
    if bool(user) != bool(password):
        raise ValueError(
            "ES authentication incomplete: supply both CZJLLM_ES_USERNAME "
            "and CZJLLM_ES_PASSWORD in a private runtime environment"
        )
    if os.getenv("CZJLLM_ENV", "").strip().lower() in {"production", "prod"}:
        if not user or not password or not str(config.get("es_host") or "").strip():
            raise ValueError(
                "ES production connection requires private host, username and password"
            )
    return config


def validate_sql_config(config):
    """For production profiles, never silently fall back to an interactive prompt."""
    if not isinstance(config, Mapping):
        raise ValueError("SQL configuration must be a mapping")
    if os.getenv("CZJLLM_ENV", "").strip().lower() in {"production", "prod"}:
        if config.get("username") and not config.get("password"):
            raise ValueError(
                "SQL password missing for production profile; configure the "
                "corresponding CZJLLM_SQL_*_PASSWORD environment variable"
            )
    return config
