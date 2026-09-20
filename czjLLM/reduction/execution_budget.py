"""Thread-safe, process-local capacity for leaf execution workers.

The budget coordinates workers within one Python process only.  It is not a
distributed semaphore and deliberately owns no executor or scheduling policy.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from threading import Condition
from typing import Iterator


def _require_positive_int(value: object, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


@dataclass(frozen=True)
class ExecutionBudgetSnapshot:
    capacity: int
    in_use: int
    available: int
    peak_in_use: int


class ExecutionBudget:
    """Grant partial worker leases without exceeding immutable capacity."""

    def __init__(self, capacity: int):
        self._capacity = _require_positive_int(capacity, "capacity")
        self._available = capacity
        self._peak_in_use = 0
        self._condition = Condition()

    @property
    def capacity(self) -> int:
        return self._capacity

    @contextmanager
    def lease(self, requested: int) -> Iterator[int]:
        requested = _require_positive_int(requested, "requested")
        with self._condition:
            self._condition.wait_for(lambda: self._available > 0)
            granted = min(requested, self._available, self._capacity)
            self._available -= granted
            self._peak_in_use = max(
                self._peak_in_use, self._capacity - self._available
            )
        try:
            yield granted
        finally:
            with self._condition:
                self._available += granted
                self._condition.notify_all()

    def snapshot(self) -> ExecutionBudgetSnapshot:
        with self._condition:
            return ExecutionBudgetSnapshot(
                capacity=self._capacity,
                in_use=self._capacity - self._available,
                available=self._available,
                peak_in_use=self._peak_in_use,
            )
