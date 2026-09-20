"""Dependency-light guards for the production execution-budget call sites."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _function(path, name):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    return next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)


def _called_names(node):
    return [
        call.func.id
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
    ]


def test_call_llm_api_routes_both_modes_through_budgeted_leaf_helper():
    node = _function("czjLLM/prompt_pipeline/pipeline_controller.py", "call_llm_api")

    assert _called_names(node).count("_run_multicore_leaf_batch") == 2
    assert "multicoreJob" not in _called_names(node)


def test_multicore_helper_holds_lease_around_pool_creation_and_run():
    node = _function("czjLLM/prompt_pipeline/pipeline_controller.py", "_run_multicore_leaf_batch")
    calls = _called_names(node)

    assert "lease_execution_workers" in calls
    assert "multicoreJob" in calls


def test_streaming_consumer_routes_run_round_through_budgeted_helper():
    consumer = _function("czjLLM/prompt_pipeline/pipeline_controller.py", "llm_stream_consumer")
    helper = _function("czjLLM/prompt_pipeline/pipeline_controller.py", "_run_legacy_leaf_round")

    assert "_run_legacy_leaf_round" in _called_names(consumer)
    assert "run_round" not in _called_names(consumer)
    assert "lease_execution_workers" in _called_names(helper)
    assert "run_round" in _called_names(helper)


def test_row_producer_caps_threads_without_acquiring_leaf_lease():
    node = _function("czjLLM/sql_mode/runtime/producer.py", "produce_rows")
    calls = _called_names(node)

    assert "cap_orchestration_workers" in calls
    assert "ThreadPoolExecutor" in calls
    assert "lease_execution_workers" not in calls
