"""Platform-neutral monitoring event vocabulary and bounded public projection.

No GUI, HTTP, filesystem, model, or sink dependencies. The public projection
deliberately excludes raw logs, paths, prompts, exception text and repair data.
Event counters are observations, never independent SQL/ES acknowledgement.
"""
from dataclasses import dataclass
import time

MAX_COUNT = (1 << 53) - 1
MAX_ELAPSED = 1e9


@dataclass
class MonitorEvents:
    INC_SCHED: str = "inc_sched"
    INC_DONE: str = "inc_done"
    LOG: str = "log"
    CLOSE: str = "close"
    SET_TOTAL: str = "set_total"
    RECHECK: str = "recheck"
    REDUCTION: str = "reduction"
    AUDIT_PATH: str = "audit_path"
    QUALITY_PATH: str = "quality_path"
    RECOVERY_METER: str = "recovery_meter"


def _count(value):
    if type(value) is not int or not 0 <= value <= MAX_COUNT:
        raise ValueError("invalid monitor counter")
    return value


class MonitorProjection:
    """Single-consumer numeric state. No event history or untrusted metadata."""

    def __init__(self, total, *, clock=time.monotonic):
        self.total = _count(total)
        self.scheduled = self.completed = self.rejected_events = 0
        self.closed = False
        self._clock = clock
        self._started = clock()

    def apply(self, kind, payload):
        if self.closed:
            return False
        if kind == MonitorEvents.CLOSE:
            if payload is not None:
                return self._reject()
            self.closed = True
            return True
        try:
            if kind == MonitorEvents.SET_TOTAL:
                self.total = _count(payload)
            elif kind == MonitorEvents.INC_SCHED:
                self.scheduled = _count(self.scheduled + _count(payload))
            elif kind == MonitorEvents.INC_DONE:
                self.completed = _count(self.completed + _count(payload))
            else:
                # Other event types are private or not part of this projection.
                return False
        except ValueError:
            return self._reject()
        return True

    def _reject(self):
        self.rejected_events = min(MAX_COUNT, self.rejected_events + 1)
        return False

    def snapshot(self):
        elapsed = self._clock() - self._started
        elapsed = elapsed if 0 <= elapsed <= MAX_ELAPSED else None
        return {
            "schema": 1, "total": self.total, "scheduled": self.scheduled,
            "completed": self.completed, "closed": self.closed,
            "elapsed_s": elapsed, "rejected_events": self.rejected_events,
            "scope": "observed_run_events",
            "sink_readback_verified": False,
        }
