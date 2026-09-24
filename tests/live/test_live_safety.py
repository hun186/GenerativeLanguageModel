import pytest

from .safety import live_enabled, require_safe_es_index, require_safe_sql_table


def test_live_opt_in_is_strict_and_off_by_default():
    assert not live_enabled({})
    assert not live_enabled({"CZJLLM_RUN_LIVE_E2E": "0"})
    assert live_enabled({"CZJLLM_RUN_LIVE_E2E": "1"})


def test_unsafe_sql_namespace_is_refused_before_connection():
    with pytest.raises(ValueError, match="czjllm_e2e_"):
        require_safe_sql_table("production_customers")
    assert require_safe_sql_table("czjllm_e2e_source") == "czjllm_e2e_source"


def test_unsafe_es_namespace_is_refused_before_connection():
    with pytest.raises(ValueError, match="czjllm-e2e-"):
        require_safe_es_index("production-events")
    assert require_safe_es_index("czjllm-e2e-source") == "czjllm-e2e-source"
