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
    assert _llm_round_debug_enabled("false") is False
    assert _llm_round_debug_enabled(True) is True


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


def test_windows_spawn_overlap_fallback_runs_round_with_threads_when_join_cannot_clear(monkeypatch):
    import czjLLM.prompt_pipeline.round_runner as rr

    monkeypatch.setattr(rr.sys, "platform", "win32")
    monkeypatch.setattr(rr, "_active_children_count", lambda: 1)
    monkeypatch.setattr(rr, "_join_existing_children_once", lambda timeout_sec: 1)
    jobs = [_Job(lambda: 1), _Job(lambda: 2)]
    out = run_round(jobs, n_proc=2, timeout_sec=5)

    assert [item["raw"] for item in out] == [1, 2]


def test_windows_spawn_overlap_thread_fallback_preserves_concurrency(monkeypatch):
    import czjLLM.prompt_pipeline.round_runner as rr

    monkeypatch.setattr(rr.sys, "platform", "win32")
    monkeypatch.setattr(rr, "_active_children_count", lambda: 1)
    monkeypatch.setattr(rr, "_join_existing_children_once", lambda timeout_sec: 1)
    started = []

    def slow(value):
        started.append(value)
        time.sleep(0.2)
        return value

    jobs = [_Job(lambda i=i: slow(i)) for i in range(4)]
    t0 = time.monotonic()
    out = run_round(jobs, n_proc=4, timeout_sec=5)

    assert [item["raw"] for item in out] == [0, 1, 2, 3]
    assert len(started) == 4
    assert time.monotonic() - t0 < 0.6


def test_windows_spawn_overlap_join_clear_allows_pool(monkeypatch):
    import czjLLM.prompt_pipeline.round_runner as rr

    monkeypatch.setattr(rr.sys, "platform", "win32")
    monkeypatch.setattr(rr, "_active_children_count", lambda: 1)
    monkeypatch.setattr(rr, "_join_existing_children_once", lambda timeout_sec: 0)

    assert rr._should_use_thread_pool_to_avoid_windows_spawn_overlap() is False


def test_windows_thread_round_observes_out_of_order_completion_but_returns_input_order(monkeypatch):
    """A slow first Future must not conceal fast later completions."""
    import threading
    import czjLLM.prompt_pipeline.round_runner as rr

    monkeypatch.setattr(rr.sys, "platform", "win32")
    first_started = threading.Event()
    unblock_first = threading.Event()
    second_finished = threading.Event()
    outcome = {}

    def slow_first():
        first_started.set()
        if not unblock_first.wait(4.0):
            raise RuntimeError("fixture release not observed")
        return "first"

    def fast_second():
        assert first_started.wait(3.0)
        second_finished.set()
        return "second"

    def run():
        try:
            outcome["results"] = rr.run_round(
                [_Job(slow_first), _Job(fast_second)], n_proc=2,
                timeout_sec=4.0,
            )
        except BaseException as exc:
            outcome["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        assert second_finished.wait(3.0)
        deadline = time.monotonic() + 2.0
        while rr.CONSUMER_STATE.get("thread_round_completed_count") != 1:
            if time.monotonic() >= deadline:
                pytest.fail("fast Future did not report completion behind slow first")
            time.sleep(0.005)
        assert worker.is_alive()  # first Future still blocked
        assert rr.CONSUMER_STATE["thread_round_drain_active"] is False
    finally:
        unblock_first.set()
        worker.join(timeout=4.0)
    assert not worker.is_alive()
    assert "error" not in outcome
    assert [entry["raw"] for entry in outcome["results"]] == [
        "first", "second",
    ]
    assert rr.CONSUMER_STATE["thread_round_completed_count"] == 2
    assert rr.CONSUMER_STATE["last_round_timed_out"] is False


def test_windows_thread_timeout_cancels_only_not_started_and_drains_running(monkeypatch):
    """A timed-out round must never claim to have killed an active Thread."""
    import threading
    import czjLLM.prompt_pipeline.round_runner as rr

    monkeypatch.setattr(rr.sys, "platform", "win32")
    entered = [threading.Event(), threading.Event()]
    unblock = threading.Event()
    third_ran = threading.Event()
    outcome = {}

    def blocked(i):
        entered[i].set()
        if not unblock.wait(4.0):
            raise RuntimeError("fixture release not observed")
        return i

    def queued():
        third_ran.set()
        return 3

    def run():
        try:
            rr.run_round(
                [_Job(lambda: blocked(0)), _Job(lambda: blocked(1)),
                 _Job(queued)],
                n_proc=2, timeout_sec=1.0,
            )
        except BaseException as exc:
            outcome["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        assert all(event.wait(2.0) for event in entered)
        deadline = time.monotonic() + 3.0
        while not rr.CONSUMER_STATE.get("thread_round_drain_active"):
            if time.monotonic() >= deadline:
                pytest.fail("ThreadPool deadline did not report active draining")
            time.sleep(0.005)
        assert worker.is_alive()  # BatchRunTimeout waits for both live calls
        assert rr.CONSUMER_STATE["thread_round_timeout_running"] == 2
        assert rr.CONSUMER_STATE["thread_round_cancelled_before_start"] == 1
        assert not third_ran.is_set()
    finally:
        unblock.set()
        worker.join(timeout=4.0)
    assert not worker.is_alive()
    err = outcome.get("error")
    assert isinstance(err, BatchRunTimeout)
    assert (err.finished, err.total) == (0, 3)
    assert rr.CONSUMER_STATE["last_round_timed_out"] is True
    assert rr.CONSUMER_STATE["thread_round_drain_active"] is False
    assert not third_ran.is_set()  # No late duplicate dispatch


def test_windows_batch_timeout_counts_fast_completed_futures_behind_slow_first(monkeypatch):
    """finished=N is observed Future completion, not a prefix / sink ACK."""
    import threading
    import czjLLM.prompt_pipeline.round_runner as rr

    monkeypatch.setattr(rr.sys, "platform", "win32")
    first_started = threading.Event()
    unblock_first = threading.Event()
    fast_done = threading.Event()
    outcome = {}

    def slow():
        first_started.set()
        if not unblock_first.wait(4.0):
            raise RuntimeError("fixture release not observed")
        return 1

    def fast():
        assert first_started.wait(2.0)
        fast_done.set()
        return 2

    def run():
        try:
            rr.run_round([_Job(slow), _Job(fast)], n_proc=2, timeout_sec=1.0)
        except BaseException as exc:
            outcome["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        assert fast_done.wait(2.0)
        deadline = time.monotonic() + 3.0
        while not rr.CONSUMER_STATE.get("thread_round_drain_active"):
            if time.monotonic() >= deadline:
                pytest.fail("timeout was not observed")
            time.sleep(0.005)
        assert rr.CONSUMER_STATE["thread_round_completed_count"] == 1
    finally:
        unblock_first.set()
        thread.join(timeout=4.0)
    assert not thread.is_alive()
    err = outcome.get("error")
    assert isinstance(err, BatchRunTimeout)
    assert (err.finished, err.total) == (1, 2)
    assert rr.CONSUMER_STATE["thread_round_drain_active"] is False


def test_windows_worker_raised_timeout_is_not_misclassified_as_batch_deadline(monkeypatch):
    import czjLLM.prompt_pipeline.round_runner as rr

    monkeypatch.setattr(rr.sys, "platform", "win32")

    def worker_timeout():
        raise TimeoutError("simulated LLM exception, not round deadline")

    with pytest.raises(TimeoutError, match="simulated LLM exception"):
        rr.run_round([_Job(worker_timeout), _Job(lambda: "done")],
                     n_proc=2, timeout_sec=3.0)
    assert rr.CONSUMER_STATE["last_round_timed_out"] is False
    assert rr.CONSUMER_STATE["thread_round_drain_active"] is False
