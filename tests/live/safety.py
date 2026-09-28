from __future__ import annotations

import os


TRUE_VALUES = {"1", "true", "yes", "on"}
SQL_PREFIX = "czjllm_e2e_"
ES_PREFIX = "czjllm-e2e-"


def live_enabled(environ=None) -> bool:
    env = os.environ if environ is None else environ
    return str(env.get("CZJLLM_RUN_LIVE_E2E", "")).strip().lower() in TRUE_VALUES


def require_safe_sql_table(name: str) -> str:
    value = str(name or "").strip()
    if not value.lower().startswith(SQL_PREFIX):
        raise ValueError(f"live SQL table must start with {SQL_PREFIX!r}")
    return value


def require_safe_es_index(name: str) -> str:
    value = str(name or "").strip()
    if not value.lower().startswith(ES_PREFIX):
        raise ValueError(f"live ES index must start with {ES_PREFIX!r}")
    return value
