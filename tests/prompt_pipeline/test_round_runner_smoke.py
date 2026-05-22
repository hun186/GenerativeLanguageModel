import time

import pytest

from czjLLM.prompt_pipeline.round_runner import BatchRunTimeout, CONSUMER_STATE, run_round


class _Job:
    def __init__(self, fn):
        self._fn = fn

    def proc(self):
        return self._fn()


def test_run_round_single_process_success_updates_state():
    jobs = [_Job(lambda: 1), _Job(lambda: 2), _Job(lambda: 3)]

    out = run_round(jobs, n_proc=1, timeout_sec=5)

    assert out == [1, 2, 3]
    assert CONSUMER_STATE["pool_alive"] is False
    assert CONSUMER_STATE["last_dispatch_ts"] > 0


def test_run_round_single_process_timeout_raises_batch_timeout():
    jobs = [_Job(lambda: time.sleep(1.1) or 1), _Job(lambda: 2)]

    with pytest.raises(BatchRunTimeout):
        run_round(jobs, n_proc=1, timeout_sec=1)
