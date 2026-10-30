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
        hosts = config.get("hosts")
        if hosts:
            # resolve_es_connection uses hosts ahead of es_host.
            entries = hosts if isinstance(hosts, (list, tuple)) else [hosts]
            valid_destination = bool(entries) and all(
                bool(entry.strip()) if isinstance(entry, str)
                else bool(str(entry.get("host") or "").strip())
                if isinstance(entry, Mapping) else False
                for entry in entries
            )
        else:
            valid_destination = bool(str(config.get("es_host") or "").strip())
        if not user or not password or not valid_destination:
            raise ValueError(
                "ES production connection requires private host, username and password"
            )
    return config


def validate_sql_config(config):
    """For production profiles, never silently fall back to an interactive prompt."""
    if not isinstance(config, Mapping):
        raise ValueError("SQL configuration must be a mapping")
    if os.getenv("CZJLLM_ENV", "").strip().lower() in {"production", "prod"}:
        if "username" in config and not all(
            (config.get("server"), config.get("username"), config.get("password"))
        ):
            raise ValueError(
                "SQL production connection requires a private server, username "
                "and the corresponding CZJLLM_SQL_*_PASSWORD"
            )
    return config
