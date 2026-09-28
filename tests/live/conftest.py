from __future__ import annotations

import os
import uuid

import pytest

from .safety import live_enabled, require_safe_es_index, require_safe_sql_table


def _required(names):
    values = {}
    for name in names:
        value = os.getenv(name)
        if not value:
            pytest.skip(f"missing required live configuration: {name}")
        values[name] = value
    return values


@pytest.fixture
def live_opt_in():
    if not live_enabled():
        pytest.skip("live tests require explicit CZJLLM_RUN_LIVE_E2E=1 opt-in")


@pytest.fixture
def live_run_id(live_opt_in):
    return f"e2e-{uuid.uuid4()}"


@pytest.fixture
def live_llm_config(live_opt_in):
    values = _required(("LLM_BASE_URL", "LLM_MODEL_NAME", "LLM_API_KEY"))
    return {"base_url": values["LLM_BASE_URL"], "model_name": values["LLM_MODEL_NAME"], "api_key": values["LLM_API_KEY"]}


@pytest.fixture
def live_sql_config(live_opt_in):
    values = _required(("LIVE_SQL_CONN_STR", "LIVE_SQL_SOURCE_TABLE", "LIVE_SQL_TARGET_TABLE"))
    values["LIVE_SQL_SOURCE_TABLE"] = require_safe_sql_table(values["LIVE_SQL_SOURCE_TABLE"])
    values["LIVE_SQL_TARGET_TABLE"] = require_safe_sql_table(values["LIVE_SQL_TARGET_TABLE"])
    return values


@pytest.fixture
def live_es_config(live_opt_in):
    values = _required(("LIVE_ES_URL", "LIVE_ES_SOURCE_INDEX", "LIVE_ES_TARGET_INDEX"))
    values["LIVE_ES_SOURCE_INDEX"] = require_safe_es_index(values["LIVE_ES_SOURCE_INDEX"])
    values["LIVE_ES_TARGET_INDEX"] = require_safe_es_index(values["LIVE_ES_TARGET_INDEX"])
    return values
