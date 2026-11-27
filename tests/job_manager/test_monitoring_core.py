"""Headless portable monitoring projection regressions."""
import pytest

from czjLLM.job_manager.monitoring_core import MAX_COUNT, MonitorEvents, MonitorProjection
from czjLLM.job_manager.win_gui import _GuiEvents


def test_windows_vocabulary_remains_identical():
    assert _GuiEvents is MonitorEvents
    assert _GuiEvents.INC_SCHED == "inc_sched"
    assert _GuiEvents.RECOVERY_METER == "recovery_meter"


def test_observed_counters_and_elapsed_are_not_sink_readback():
    now = [10]
    monitor = MonitorProjection(12, clock=lambda: now[0])
    assert monitor.apply(MonitorEvents.INC_SCHED, 5)
    assert monitor.apply(MonitorEvents.INC_DONE, 3)
    assert monitor.apply(MonitorEvents.SET_TOTAL, 15)
    now[0] = 25
    view = monitor.snapshot()
    assert (view["scheduled"], view["completed"], view["total"]) == (5, 3, 15)
    assert view["elapsed_s"] == 15
    assert view["sink_readback_verified"] is False
    assert monitor.apply(MonitorEvents.CLOSE, None)
    assert not monitor.apply(MonitorEvents.INC_DONE, 1)
    assert monitor.snapshot()["completed"] == 3


@pytest.mark.parametrize("value", [True, -1, "5", 2.5, MAX_COUNT + 1])
def test_invalid_counters_are_rejected_atomically(value):
    monitor = MonitorProjection(10)
    assert not monitor.apply(MonitorEvents.INC_SCHED, value)
    assert monitor.snapshot()["scheduled"] == 0
    assert monitor.snapshot()["rejected_events"] == 1


def test_private_events_and_overflow_do_not_leak():
    monitor = MonitorProjection(10)
    for event in (MonitorEvents.LOG, MonitorEvents.AUDIT_PATH,
                  MonitorEvents.QUALITY_PATH, MonitorEvents.RECOVERY_METER,
                  MonitorEvents.RECHECK, MonitorEvents.REDUCTION, "unknown"):
        assert not monitor.apply(event, "PRIVATE_PAYLOAD")
    assert monitor.apply(MonitorEvents.INC_DONE, MAX_COUNT)
    assert not monitor.apply(MonitorEvents.INC_DONE, 1)
    view = monitor.snapshot()
    assert view["completed"] == MAX_COUNT
    assert "PRIVATE_PAYLOAD" not in repr(view)
