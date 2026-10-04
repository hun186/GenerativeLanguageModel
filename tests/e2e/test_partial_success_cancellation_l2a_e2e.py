"""One L2a production-boundary E2E for partial collection results and cancellation."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from types import SimpleNamespace

import pytest

from czjLLM.reduction import (
    AggregateOutput, CollectionManifest, EventCancellationSignal, ExecutableResult,
    ExecutionCancelled, ExecutionContext, ExecutionError, LogicalWorkUnit,
    PartialSuccessPolicy, ProductionTaskRuntime, ReductionStage, TaskExecutable,
    parse_reduction_config,
)
from czjLLM.reduction.execution_budget import ExecutionBudget

pytestmark = pytest.mark.e2e


class CollectionTaskWorker:
    executor_type = "collection_task"
    contract_version = "collection-task-test-v1"

    def __init__(self, task):
        self.task = TaskExecutable(task)
        self.seen = []

    def execute(self, item, context):
        self.seen.append(item.logical_id)
        if item.logical_id == "B":
            raise ExecutionError("deterministic member boundary failure")
        result = self.task.execute(item.payload["text"], context)
        return ExecutableResult(
            f"{item.logical_id}:{result.output}", self.executor_type, self.contract_version
        )

    def fingerprint_metadata(self, context):
        return {"type": self.executor_type, "contract_version": self.contract_version,
                "task": self.task.fingerprint_metadata(context)}


def test_partial_success_and_cooperative_cancellation_l2a(fake_openai, tmp_path):
    budget = ExecutionBudget(3)
    root = SimpleNamespace(
        task="ROOT", taskSetting={}, model_spec_name="e2e-model",
        model_spec=fake_openai.model_spec, max_tokens=4096, think_mode=False,
        PGMSubDir=str(tmp_path), llm_call_audit_run_id="l2a-e2e",
        llm_call_audit_path=str(tmp_path / "audit.csv"), _execution_budget=budget,
    )
    manifest = CollectionManifest("four-member-collection", tuple(
        LogicalWorkUnit(name, {"text": f"ROW_ID={name}"}) for name in "ABCD"
    ))
    config = parse_reduction_config({"enabled": True, "profile": "concat_text"})
    worker = CollectionTaskWorker("E2E_SUMMARY")
    result = ReductionStage(
        worker, config, worker_parallelism=3,
        failure_policy=PartialSuccessPolicy("allow_partial", 3, .75),
    ).execute(manifest.units, ExecutionContext(root, ProductionTaskRuntime(root)))

    assert len(fake_openai.requests) == 3
    assert result.worker_attempt_count == 4 and result.worker_success_count == 3
    assert result.worker_failure_count == 1 and result.partial_result is True
    assert result.payload.index("A:") < result.payload.index("C:") < result.payload.index("D:")
    failure = result.provenance["partial_success"]["failures"][0]
    assert failure["logical_id"] == "B" and failure["input_index"] == 1
    assert result.provenance["partial_success"]["incomplete"] is True
    assert result.audit["failed_member_count"] == 1
    assert result.metrics["worker_success_ratio"] == .75
    assert result.warnings == ("partial_success_accepted: succeeded=3 attempted=4 failed=1",)
    assert not any(token in repr(failure) for token in (
        "ROW_ID", "E2E_SUMMARY", "e2e-dummy-key", fake_openai.base_url
    ))

    aggregate = AggregateOutput(
        manifest, "summary", result.payload,
        provenance={"reduction_stage": dict(result.provenance)},
    )
    assert aggregate.manifest_fingerprint == manifest.fingerprint
    assert len(manifest.units) == 4
    assert aggregate.provenance["reduction_stage"]["partial_success"]["failures"][0]["logical_id"] == "B"

    cancel_event = Event(); release = Event(); started = Barrier(3); cancel_budget = ExecutionBudget(2)
    class BlockingWorker:
        executor_type = "blocking"
        contract_version = "blocking-v1"
        def execute(self, item, context):
            with cancel_budget.lease(1):
                started.wait(timeout=3); release.wait(timeout=3)
                return ExecutableResult(item, self.executor_type, self.contract_version)
        def fingerprint_metadata(self, context):
            return {"type": self.executor_type, "contract_version": self.contract_version}

    cancel_context = ExecutionContext(cancellation=EventCancellationSignal(cancel_event))
    cancel_stage = ReductionStage(BlockingWorker(), config, worker_parallelism=2)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(cancel_stage.execute, list("abcdef"), cancel_context)
        started.wait(timeout=3); cancel_event.set(); release.set()
        with pytest.raises(ExecutionCancelled):
            pending.result(timeout=5)
    snapshot = cancel_budget.snapshot()
    assert snapshot.in_use == 0 and snapshot.peak_in_use <= 2
