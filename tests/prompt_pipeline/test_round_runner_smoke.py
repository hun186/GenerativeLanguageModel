import time

import pytest

from czjLLM.prompt_pipeline.round_runner import (
    BatchRunTimeout,
    CONSUMER_STATE,
    _debug_round_message,
    _llm_round_debug_enabled,
    run_round,
)


class _Job:
    def __init__(self, fn):
        self._fn = fn
        self.promptFile = "sample_prompt.txt"

    def proc(self):
        return self._fn()


def test_run_round_single_process_success_updates_state():
    jobs = [_Job(lambda: 1), _Job(lambda: 2), _Job(lambda: 3)]

    out = run_round(jobs, n_proc=1, timeout_sec=5)

    assert [item["raw"] for item in out] == [1, 2, 3]
    assert all(item["ok"] for item in out)
    assert CONSUMER_STATE["pool_alive"] is False
    assert CONSUMER_STATE["last_dispatch_ts"] > 0


def test_run_round_single_process_timeout_raises_batch_timeout():
    jobs = [_Job(lambda: time.sleep(1.1) or 1), _Job(lambda: 2)]

    with pytest.raises(BatchRunTimeout):
        run_round(jobs, n_proc=1, timeout_sec=1)


def test_llm_round_debug_env_flag(monkeypatch):
    monkeypatch.delenv("CZJLLM_LLM_ROUND_DEBUG", raising=False)
    assert _llm_round_debug_enabled() is False

    monkeypatch.setenv("CZJLLM_LLM_ROUND_DEBUG", "1")
    assert _llm_round_debug_enabled() is True

    monkeypatch.setenv("CZJLLM_LLM_ROUND_DEBUG", "true")
    assert _llm_round_debug_enabled() is True


def test_debug_round_message_contains_multiprocessing_context():
    jobs = [_Job(lambda: 1), _Job(lambda: 2)]

    message = _debug_round_message(jobs, n_proc=2, timeout_sec=5, phase="before_pool")

    assert "phase=before_pool" in message
    assert "multiprocessing_start_method=" in message
    assert "active_children=" in message
    assert "pool_processes=2" in message
    assert "worker_target=czjLLM.prompt_pipeline.round_runner._run_prompt_job" in message
    assert "sample_prompt.txt" in message


def test_debug_round_message_includes_exception_details():
    jobs = [_Job(lambda: 1)]
    error = PermissionError(5, "Access is denied")

    message = _debug_round_message(jobs, n_proc=2, timeout_sec=5, phase="exception", error=error)

    assert "phase=exception" in message
    assert "error_type=builtins.PermissionError" in message
    assert "error_repr=PermissionError" in message
