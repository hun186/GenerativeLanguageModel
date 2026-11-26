import pytest

from czjLLM.prompt_pipeline.dispatch_parallelism import (
    configured_endpoint_concurrency_limit,
    configured_model_process_parallelism,
)


@pytest.mark.parametrize("count", [1, 2, 4, 8])
@pytest.mark.parametrize("factor", [1, 2, 3])
def test_worker_multiplier_scales_with_available_endpoint_count(count, factor):
    urls = [f"http://gpu{i}.invalid/v1" for i in range(count)]
    assert configured_model_process_parallelism({
        "base_url": urls, "workers_per_endpoint": factor,
    }) == count * factor


def test_worker_multiplier_deduplicates_and_supports_single_string():
    url = "http://gpu.invalid/v1"
    for urls in (url, [url, url]):
        assert configured_model_process_parallelism({
            "base_url": urls, "workers_per_endpoint": 2,
        }) == 2


def test_fixed_worker_budget_wins_and_legacy_remains_auto():
    assert configured_model_process_parallelism({
        "nProcess": 2, "workers_per_endpoint": 1, "base_url": ["a", "b", "c", "d"],
    }) == 2
    assert configured_model_process_parallelism({"base_url": ["a", "b"]}) == 0
    assert configured_endpoint_concurrency_limit({}) is None


@pytest.mark.parametrize("value", [True, False, 0, -1, "2", 1.5, None])
def test_new_options_reject_invalid_values(value):
    with pytest.raises(ValueError, match="workers_per_endpoint"):
        configured_model_process_parallelism({"base_url": ["a"], "workers_per_endpoint": value})
    with pytest.raises(ValueError, match="max_concurrent_per_endpoint"):
        configured_endpoint_concurrency_limit({"max_concurrent_per_endpoint": value})


def test_invalid_or_remote_multiplier_rejected():
    for urls in ([], None, [""]):
        with pytest.raises(ValueError, match="base_url"):
            configured_model_process_parallelism({"base_url": urls, "workers_per_endpoint": 1})
    with pytest.raises(ValueError, match="on-premises"):
        configured_model_process_parallelism({
            "base_url": ["a"], "workers_per_endpoint": 1, "on_premises": False,
        })
