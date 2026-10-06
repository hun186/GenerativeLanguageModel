from pathlib import Path
from types import SimpleNamespace
import json
import threading

import pytest

from czjLLM.reduction.execution import ExecutionCancelled
from czjLLM.reduction.production_control import (
    build_production_execution_context, ensure_execution_cancel_event,
    ensure_production_observer, execution_cancel_requested,
    finish_legacy_merge_item, request_execution_cancel,
    try_begin_legacy_merge_item,
)


def _ctx(tmp_path: Path):
    return SimpleNamespace(PGMSubDir=str(tmp_path), mode="sql", task="safe-task",
                           model_spec_name="model", model_spec={}, max_tokens=10,
                           taskSetting={"safe-task": {"task": "safe-task", "InputCutLen": 100}})


def test_root_event_idempotent_request_and_context_bridge(tmp_path):
    ctx = _ctx(tmp_path)
    event = ensure_execution_cancel_event(ctx)
    assert event is ensure_execution_cancel_event(ctx)
    assert request_execution_cancel(ctx, source="gui") is True
    assert request_execution_cancel(ctx, source="UNTRUSTED SECRET") is False
    assert event.is_set() and execution_cancel_requested(ctx)
    execution = build_production_execution_context(ctx, observability_tags={"collection_id": "c-1"})
    with pytest.raises(ExecutionCancelled):
        execution.raise_if_cancelled()


def test_observer_is_thread_safe_bounded_and_payload_free(tmp_path):
    ctx = _ctx(tmp_path)
    observer = ensure_production_observer(ctx)
    secret = "SECRET RAW PROMPT sk-very-secret-key https://private-endpoint.example Server=secret"

    def emit():
        observer.emit("reduction_member_failed", {
            "logical_id": "member-1", "error_type": "ExecutionError",
            "reason": "execution_error", "prompt": secret,
        })

    threads = [threading.Thread(target=emit) for _ in range(10)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    for _ in range(12): observer.emit("reduction_member_attempted", {})
    for _ in range(2): observer.emit("reduction_member_succeeded", {})
    observer.emit("reduction_stage_completed", {"attempted": 12, "succeeded": 2, "failed": 10})
    snapshot = observer.snapshot()
    assert snapshot["members_failed"] == 10
    assert snapshot["members_attempted"] == 12
    assert snapshot["members_succeeded"] == 2
    content = observer.path.read_text(encoding="utf-8")
    assert secret not in content
    assert all(json.loads(line)["schema_version"] == 1 for line in content.splitlines())
    assert "reduction_member_attempted" not in content
    assert "reduction_member_succeeded" not in content


def test_live_gui_snapshots_are_throttled_but_diagnostics_are_immediate(tmp_path):
    class GUI:
        def __init__(self): self.snapshots = []
        def update_reduction_stats(self, stats, final=False):
            self.snapshots.append((dict(stats), final))

    ctx = _ctx(tmp_path)
    ctx.gui_handle = GUI()
    observer = ensure_production_observer(ctx)
    for _ in range(19):
        observer.emit("reduction_member_attempted", {})
    assert len(ctx.gui_handle.snapshots) <= 1
    observer.emit("cancellation_requested", {"cancel_source": "external"})
    assert ctx.gui_handle.snapshots[-1][0]["cancellation_requested"] == 1


def test_operational_state_does_not_change_fingerprint(tmp_path):
    from czjLLM.reduction.execution import TaskExecutable, executable_semantic_fingerprint
    ctx = _ctx(tmp_path)
    before = executable_semantic_fingerprint(TaskExecutable("safe-task"),
                                             build_production_execution_context(ctx))
    request_execution_cancel(ctx, source="external")
    after = executable_semantic_fingerprint(TaskExecutable("safe-task"),
                                            build_production_execution_context(ctx))
    assert before == after


def test_stage_member_counters_survive_require_all_failure(tmp_path):
    from czjLLM.reduction import (
        ExecutableResult, ExecutionError, ReductionStage, parse_reduction_config,
    )
    class Worker:
        executor_type = "test"; contract_version = "v1"
        def execute(self, item, context):
            if item == "bad": raise ExecutionError("payload must not be observed")
            return ExecutableResult(item, self.executor_type, self.contract_version)
        def fingerprint_metadata(self, context): return {"type": "test"}
    ctx = _ctx(tmp_path)
    context = build_production_execution_context(ctx)
    stage = ReductionStage(Worker(), parse_reduction_config(
        {"enabled": True, "profile": "concat_text"}
    ))
    with pytest.raises(ExecutionError):
        stage.execute(["ok", "bad", "never"], context)
    stats = ensure_production_observer(ctx).snapshot()
    assert stats["members_attempted"] == 2
    assert stats["members_succeeded"] == 1
    assert stats["members_failed"] == 1
    assert stats["stages_failed"] == 1 and stats["stages_completed"] == 0


def test_cancellation_request_does_not_retroactively_change_terminal_completion(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.run_status = "completed"
    observer = ensure_production_observer(ctx)
    observer.emit("run_completed", {"attempted": 1, "succeeded": 1, "failed": 0})
    request_execution_cancel(ctx, source="external")
    assert ctx.run_status == "completed"
    assert observer.snapshot()["run_status"] == "completed"



def test_legacy_merge_activity_is_distinct_from_reduction_stage_counters(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.merge_slices = True
    observer = ensure_production_observer(ctx)
    assert observer.snapshot()["activity_mode"] == "legacy_merge_slices"

    observer.emit("legacy_merge_started", {})
    observer.emit("legacy_merge_completed", {})
    observer.emit("legacy_merge_started", {})
    observer.emit("legacy_merge_failed", {"reason": "no_output"})

    stats = observer.snapshot()
    assert stats["legacy_merges_started"] == 2
    assert stats["legacy_merges_completed"] == 1
    assert stats["legacy_merges_failed"] == 1
    assert stats["stages_started"] == 0
    assert stats["members_attempted"] == 0
    assert stats["activity_mode"] == "legacy_merge_slices"



def test_mode_transition_start_events_bypass_gui_throttle(tmp_path):
    class GUI:
        def __init__(self):
            self.snapshots = []

        def update_reduction_stats(self, stats, final=False):
            self.snapshots.append((dict(stats), final))

    legacy = _ctx(tmp_path / "legacy")
    legacy.merge_slices = True
    legacy.gui_handle = GUI()
    legacy_observer = ensure_production_observer(legacy)
    assert legacy_observer.publish_snapshot(force=True)
    before = len(legacy.gui_handle.snapshots)
    legacy_observer.emit("legacy_merge_started", {})
    assert len(legacy.gui_handle.snapshots) == before + 1
    assert legacy.gui_handle.snapshots[-1][0]["activity_mode"] == "legacy_merge_slices"
    assert legacy.gui_handle.snapshots[-1][0]["legacy_merges_started"] == 1

    reduction = _ctx(tmp_path / "reduction")
    reduction.reduction = {"enabled": True, "profile": "concat_text"}
    reduction.gui_handle = GUI()
    reduction_observer = ensure_production_observer(reduction)
    assert reduction_observer.publish_snapshot(force=True)
    before = len(reduction.gui_handle.snapshots)
    reduction_observer.emit("reduction_stage_started", {})
    assert len(reduction.gui_handle.snapshots) == before + 1
    assert reduction.gui_handle.snapshots[-1][0]["activity_mode"] == "reduction_stage"
    assert reduction.gui_handle.snapshots[-1][0]["stages_started"] == 1



def test_legacy_merge_claim_is_shared_and_failure_releases_for_retry(tmp_path):
    ctx = _ctx(tmp_path)
    item = tmp_path / "item"
    assert try_begin_legacy_merge_item(ctx, item) is True
    assert try_begin_legacy_merge_item(ctx, item) is False
    finish_legacy_merge_item(ctx, item, success=False)
    assert try_begin_legacy_merge_item(ctx, item) is True
    finish_legacy_merge_item(ctx, item, success=True)
    assert try_begin_legacy_merge_item(ctx, item) is False



@pytest.mark.parametrize(
    ("attrs", "expected"),
    [
        ({"enable_slice_merge": True}, "legacy_merge_slices"),
        ({"merge_strategy": "dict_deep"}, "legacy_merge_slices"),
        ({"merge_strategy": "slice_merge"}, "legacy_merge_slices"),
        ({"merge_strategy": "on"}, "legacy_merge_slices"),
    ],
)
def test_initial_activity_mode_honors_all_supported_slice_merge_switches(
    tmp_path, attrs, expected
):
    ctx = _ctx(tmp_path)
    for name, value in attrs.items():
        setattr(ctx, name, value)
    assert ensure_production_observer(ctx).snapshot()["activity_mode"] == expected
