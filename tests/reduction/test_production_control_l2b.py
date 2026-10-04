from pathlib import Path
from types import SimpleNamespace
import json
import threading

import pytest

from czjLLM.reduction.execution import ExecutionCancelled
from czjLLM.reduction.production_control import (
    build_production_execution_context, ensure_execution_cancel_event,
    ensure_production_observer, execution_cancel_requested,
    request_execution_cancel,
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
    observer.emit("reduction_stage_completed", {"attempted": 12, "succeeded": 2, "failed": 10})
    snapshot = observer.snapshot()
    assert snapshot["members_failed"] == 10
    assert snapshot["members_attempted"] == 12
    assert snapshot["members_succeeded"] == 2
    content = observer.path.read_text(encoding="utf-8")
    assert secret not in content
    assert all(json.loads(line)["schema_version"] == 1 for line in content.splitlines())


def test_operational_state_does_not_change_fingerprint(tmp_path):
    from czjLLM.reduction.execution import TaskExecutable, executable_semantic_fingerprint
    ctx = _ctx(tmp_path)
    before = executable_semantic_fingerprint(TaskExecutable("safe-task"),
                                             build_production_execution_context(ctx))
    request_execution_cancel(ctx, source="external")
    after = executable_semantic_fingerprint(TaskExecutable("safe-task"),
                                            build_production_execution_context(ctx))
    assert before == after
