import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from czjLLM.reduction.execution_budget import ExecutionBudget


@pytest.mark.parametrize("capacity", [0, -1, True, 1.5, "2", None])
def test_capacity_rejects_non_positive_or_non_integer_values(capacity):
    with pytest.raises(ValueError, match="positive integer"):
        ExecutionBudget(capacity)


def test_positive_capacity_and_snapshot_are_immutable_observations():
    budget = ExecutionBudget(3)

    assert budget.capacity == 3
    snapshot = budget.snapshot()
    assert (snapshot.capacity, snapshot.in_use, snapshot.available, snapshot.peak_in_use) == (3, 0, 3, 0)


@pytest.mark.parametrize("requested", [0, -1, True, "2", None])
def test_lease_rejects_invalid_requested_width(requested):
    with pytest.raises(ValueError, match="positive integer"):
        with ExecutionBudget(2).lease(requested):
            pass


def test_requested_width_is_capped_and_released_normally():
    budget = ExecutionBudget(2)
    with budget.lease(20) as granted:
        assert granted == 2
        assert budget.snapshot().in_use == 2
    assert budget.snapshot().available == 2


def test_lease_is_released_after_exception():
    budget = ExecutionBudget(2)
    with pytest.raises(RuntimeError):
        with budget.lease(2):
            raise RuntimeError("worker setup failed")
    assert budget.snapshot().in_use == 0


def test_partial_capacity_is_granted_without_waiting_for_full_request():
    budget = ExecutionBudget(4)
    with budget.lease(3):
        with budget.lease(4) as granted:
            assert granted == 1
    assert budget.snapshot().available == 4


def test_concurrent_leases_never_exceed_capacity():
    budget = ExecutionBudget(4)
    barrier = threading.Barrier(8)

    def work():
        barrier.wait()
        with budget.lease(4):
            time.sleep(0.01)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda _index: work(), range(8)))

    snapshot = budget.snapshot()
    assert snapshot.peak_in_use == 4
    assert snapshot.in_use == 0


def test_returned_capacity_wakes_a_waiting_caller():
    budget = ExecutionBudget(1)
    entered = threading.Event()

    def waiter():
        with budget.lease(1):
            entered.set()

    with budget.lease(1):
        thread = threading.Thread(target=waiter)
        thread.start()
        assert not entered.wait(0.05)
    assert entered.wait(1)
    thread.join(timeout=1)
    assert not thread.is_alive()
