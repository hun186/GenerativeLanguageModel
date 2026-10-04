from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from threading import Barrier, Event, Lock
from types import SimpleNamespace
import time

import pytest

from czjLLM.reduction import (
    EventCancellationSignal, ExecutableResult, ExecutionCancelled, ExecutionContext,
    ExecutionError, LogicalWorkUnit, MAX_MEMBER_FAILURE_DETAILS, NeverCancelled,
    PartialSuccessPolicy, PartialSuccessRejectedError, ReductionStage, TaskCallResult,
    StagePipelineExecutable, TaskExecutable, parse_reduction_config,
    parse_reduction_stage_config,
)
from czjLLM.reduction.config import ReductionConfigError
from czjLLM.reduction.execution_budget import ExecutionBudget


def reduction(controller="single_pass", **extra):
    raw = {"enabled": True, "profile": "concat_text", "controller": controller, **extra}
    if controller != "single_pass":
        raw["runtime"] = {"round_task": "unused"}
    return parse_reduction_config(raw)


class Worker:
    executor_type = "test"
    contract_version = "test-v1"

    def __init__(self, fn=lambda item: item):
        self.fn = fn
        self.calls = []

    def execute(self, item, context):
        self.calls.append(item)
        value = self.fn(item)
        if isinstance(value, BaseException):
            raise value
        return ExecutableResult(value, self.executor_type, self.contract_version)

    def fingerprint_metadata(self, context):
        return {"type": "test", "version": self.contract_version}


def test_policy_is_strict_immutable_and_default_require_all():
    policy = PartialSuccessPolicy()
    assert policy.mode == "require_all" and policy.min_success_count == 1
    with pytest.raises(FrozenInstanceError):
        policy.mode = "allow_partial"
    for kwargs in ({"mode": "best_effort"}, {"min_success_count": 0},
                   {"min_success_count": True}, {"min_success_ratio": True},
                   {"min_success_ratio": float("nan")}, {"min_success_ratio": 1.01}):
        with pytest.raises(ValueError):
            PartialSuccessPolicy(**kwargs)


def test_strict_stage_config_parses_policy_and_rejects_unknown_fields():
    base = {"worker": {"type": "task", "task": "summary"},
            "reduction": {"enabled": True, "profile": "concat_text"}}
    assert parse_reduction_stage_config(base).failure_policy == PartialSuccessPolicy()
    raw = {**base, "reduction": {**base["reduction"], "failure_policy": {
        "mode": "allow_partial", "min_success_count": 2, "min_success_ratio": .75}}}
    assert parse_reduction_stage_config(raw).failure_policy.min_success_ratio == .75
    raw["reduction"]["failure_policy"]["exception_classes"] = ["ValueError"]
    with pytest.raises(ReductionConfigError, match="Unsupported"):
        parse_reduction_stage_config(raw)


def test_failure_policy_changes_fingerprint_but_cancellation_does_not():
    worker = Worker()
    default = ReductionStage(worker, reduction())
    partial = ReductionStage(worker, reduction(), failure_policy=PartialSuccessPolicy("allow_partial", 1, .5))
    assert default.execution_fingerprint(ExecutionContext()) != partial.execution_fingerprint(ExecutionContext())
    assert partial.execution_fingerprint(ExecutionContext(cancellation=NeverCancelled())) == \
           partial.execution_fingerprint(ExecutionContext(cancellation=EventCancellationSignal(Event())))


def test_require_all_preserves_failure_and_unexpected_failure_fails_hard():
    stage = ReductionStage(Worker(lambda item: ExecutionError("safe") if item == "b" else item), reduction())
    with pytest.raises(ExecutionError, match="safe"):
        stage.execute(["a", "b", "c"], ExecutionContext())
    with pytest.raises(TypeError, match="bug"):
        ReductionStage(Worker(lambda _: TypeError("bug")), reduction(),
                       failure_policy=PartialSuccessPolicy("allow_partial")).execute(["a"], ExecutionContext())


def test_accepted_partial_preserves_order_and_safe_failure_lineage():
    units = tuple(LogicalWorkUnit(name, {"text": name}) for name in "ABCD")
    delays = {"A": .04, "C": .02, "D": .01}
    def run(unit):
        if unit.logical_id == "B":
            return ExecutionError("payload B and secret must not escape")
        time.sleep(delays[unit.logical_id])
        return unit.logical_id
    result = ReductionStage(
        Worker(run), reduction(), 4,
        failure_policy=PartialSuccessPolicy("allow_partial", 3, .75),
    ).execute(units, ExecutionContext())
    assert result.payload == "ACD"
    assert (result.worker_attempt_count, result.worker_success_count,
            result.worker_failure_count, result.partial_result) == (4, 3, 1, True)
    partial = result.provenance["partial_success"]
    assert partial["incomplete"] is True and partial["failures"][0] == {
        "round_index": 1, "input_index": 1, "logical_id": "B",
        "error_type": "ExecutionError", "reason": "execution_error"}
    assert "payload B" not in repr(partial) and "secret" not in repr(partial)
    assert result.warnings == ("partial_success_accepted: succeeded=3 attempted=4 failed=1",)


@pytest.mark.parametrize("policy", [
    PartialSuccessPolicy("allow_partial", 3, 0),
    PartialSuccessPolicy("allow_partial", 1, .75),
])
def test_partial_threshold_rejection_exposes_only_counts(policy):
    worker = Worker(lambda item: item if item in {"a", "b"} else ExecutionError("private"))
    with pytest.raises(PartialSuccessRejectedError) as caught:
        ReductionStage(worker, reduction(), failure_policy=policy).execute(
            ["a", "b", "c", "d"], ExecutionContext())
    assert (caught.value.attempted, caught.value.succeeded, caught.value.failed,
            caught.value.success_ratio) == (4, 2, 2, .5)
    assert caught.value.reason == "partial_success_threshold_not_met"
    assert "private" not in str(caught.value)


def test_zero_successes_rejected_and_plain_input_has_no_logical_id():
    with pytest.raises(PartialSuccessRejectedError):
        ReductionStage(Worker(lambda _: ExecutionError("x")), reduction(),
                       failure_policy=PartialSuccessPolicy("allow_partial")).execute(
                           ["raw"], ExecutionContext())


def test_failure_detail_bound_does_not_change_threshold_semantics():
    size = MAX_MEMBER_FAILURE_DETAILS + 7
    result = ReductionStage(
        Worker(lambda item: "ok" if item == size else ExecutionError("x")), reduction(),
        failure_policy=PartialSuccessPolicy("allow_partial", 1, 0),
    ).execute(list(range(size + 1)), ExecutionContext())
    partial = result.provenance["partial_success"]
    assert len(partial["failures"]) == MAX_MEMBER_FAILURE_DETAILS
    assert partial["failure_details_omitted"] == 7
    assert result.worker_failure_count == size
    assert partial["failures"][0]["logical_id"] is None


def test_execution_cancelled_is_never_member_failure():
    with pytest.raises(ExecutionCancelled):
        ReductionStage(Worker(lambda _: ExecutionCancelled("stop")), reduction(),
                       failure_policy=PartialSuccessPolicy("allow_partial")).execute(
                           ["a"], ExecutionContext())


@pytest.mark.parametrize("fatal_type", [TypeError, AssertionError, MemoryError])
def test_real_task_executable_programmer_faults_fail_hard(fatal_type):
    class FatalRuntime:
        def execute(self, *, task, content):
            raise fatal_type("programmer fault")
        def fingerprint_metadata(self):
            return {"runtime": "fatal-test-v1"}

    stage = ReductionStage(
        TaskExecutable("summary"), reduction(),
        failure_policy=PartialSuccessPolicy("allow_partial", 1, 0),
    )
    with pytest.raises(fatal_type, match="programmer fault"):
        stage.execute(["member"], ExecutionContext(task_runtime=FatalRuntime()))


@pytest.mark.parametrize("fatal_type", [TypeError, AssertionError])
def test_stage_pipeline_programmer_fault_aborts_without_legacy_arity_retry(fatal_type):
    calls = []
    class FatalRuntime:
        def execute(self, *, task, content):
            calls.append((task, content))
            raise fatal_type("programmer fault")
        def fingerprint_metadata(self):
            return {"runtime": "pipeline-fatal-test-v1"}

    pipeline = StagePipelineExecutable([{"name": "one", "task": "summary"}])
    root = SimpleNamespace(taskSetting={}, model_spec_name="test", max_tokens=100)
    stage = ReductionStage(
        pipeline, reduction(),
        failure_policy=PartialSuccessPolicy("allow_partial", 1, 0),
    )
    expected_type = RuntimeError if fatal_type is TypeError else AssertionError
    with pytest.raises(expected_type) as caught:
        stage.execute(["member"], ExecutionContext(root, FatalRuntime()))
    assert calls == [("summary", "member")]
    assert not isinstance(caught.value, ExecutionError)
    if fatal_type is TypeError:
        assert isinstance(caught.value, RuntimeError)
        assert isinstance(caught.value.__cause__, TypeError)
    else:
        assert isinstance(caught.value, AssertionError)


def test_stage_pipeline_operational_failure_remains_recoverable_partial_member():
    calls = []
    class OperationalRuntime:
        def execute(self, *, task, content):
            calls.append(content)
            if content == "bad":
                raise RuntimeError("ordinary transport failure")
            return TaskCallResult(f"ok:{content}", True)
        def fingerprint_metadata(self):
            return {"runtime": "pipeline-operational-test-v1"}

    pipeline = StagePipelineExecutable([{"name": "one", "task": "summary"}])
    root = SimpleNamespace(taskSetting={}, model_spec_name="test", max_tokens=100)
    result = ReductionStage(
        pipeline, reduction(),
        failure_policy=PartialSuccessPolicy("allow_partial", 1, .5),
    ).execute(["good", "bad"], ExecutionContext(root, OperationalRuntime()))
    # Ordinary stage failure retains the existing stage retry contract before
    # becoming one recoverable member failure at the outer ReductionStage.
    assert calls == ["good", "bad", "bad"]
    assert result.payload == "ok:good"
    assert (result.worker_attempt_count, result.worker_success_count,
            result.worker_failure_count, result.partial_result) == (2, 1, 1, True)
    assert result.provenance["partial_success"]["failures"][0]["error_type"] == \
        "ExecutionError"


def test_cancelled_before_start_makes_zero_calls_and_nested_context_shares_signal():
    event = Event(); event.set(); worker = Worker()
    context = ExecutionContext(cancellation=EventCancellationSignal(event))
    assert context.enter_nested_reduction().cancellation is context.cancellation
    assert context.push_pipeline_ref("x").cancellation is context.cancellation
    with pytest.raises(ExecutionCancelled):
        ReductionStage(worker, reduction()).execute(["a"], context)
    assert worker.calls == []


def test_serial_cancellation_prevents_later_item():
    event = Event()
    def run(item):
        if item == "a": event.set()
        return item
    worker = Worker(run)
    with pytest.raises(ExecutionCancelled):
        ReductionStage(worker, reduction()).execute(
            ["a", "b"], ExecutionContext(cancellation=EventCancellationSignal(event)))
    assert worker.calls == ["a"]


def test_parallel_cancellation_is_bounded_drains_workers_and_releases_budget():
    event = Event(); release = Event(); barrier = Barrier(3); lock = Lock(); started = []
    budget = ExecutionBudget(2)
    class BudgetWorker(Worker):
        def execute(self, item, context):
            with budget.lease(1):
                with lock: started.append(item)
                barrier.wait(); release.wait(2)
                return ExecutableResult(item, self.executor_type, self.contract_version)
    context = ExecutionContext(cancellation=EventCancellationSignal(event))
    stage = ReductionStage(BudgetWorker(), reduction(), worker_parallelism=2)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(stage.execute, list("abcdef"), context)
        barrier.wait(timeout=2); event.set(); release.set()
        with pytest.raises(ExecutionCancelled): future.result(timeout=3)
    assert len(started) == 2
    snapshot = budget.snapshot()
    assert snapshot.in_use == 0 and snapshot.peak_in_use <= snapshot.capacity

class RoundPreparer:
    def __init__(self, values, event=None):
        self.values = values
        self.event = event
    def prepare(self, payload, round_index, context):
        if self.event is not None:
            self.event.set()
        return list(self.values)
    def fingerprint_metadata(self, context):
        return {"type": "l2a-test-preparer", "values": list(self.values)}


def test_partial_policy_applies_independently_in_later_hierarchical_round():
    worker = Worker(lambda item: ExecutionError("later") if item == "bad" else item)
    stage = ReductionStage(
        worker, reduction("fixed_rounds", controller_options={"rounds": 2}),
        round_preparer=RoundPreparer(["two", "bad"]),
        failure_policy=PartialSuccessPolicy("allow_partial", 1, .5),
    )
    result = stage.execute(["one"], ExecutionContext())
    assert result.payload == "two"
    assert result.provenance["partial_success"]["failures"][0]["round_index"] == 2
    rejecting = ReductionStage(
        Worker(lambda item: ExecutionError("later") if item == "bad" else item),
        reduction("fixed_rounds", controller_options={"rounds": 2}),
        round_preparer=RoundPreparer(["two", "bad"]),
        failure_policy=PartialSuccessPolicy("allow_partial", 2, .5),
    )
    with pytest.raises(PartialSuccessRejectedError):
        rejecting.execute(["one"], ExecutionContext())


def test_cancellation_after_completed_round_does_not_commit_next_and_retry_resumes(tmp_path):
    event = Event()
    stage = ReductionStage(
        Worker(), reduction("fixed_rounds", controller_options={"rounds": 2}),
        round_preparer=RoundPreparer(["round-two"], event), checkpoint_root=tmp_path,
    )
    with pytest.raises(ExecutionCancelled):
        stage.execute(["round-one"], ExecutionContext(
            cancellation=EventCancellationSignal(event)))
    completed_before = sorted(tmp_path.rglob("round-*.json"))
    assert len(completed_before) == 1 and "round-0001" in completed_before[0].name

    stage = ReductionStage(
        Worker(), reduction("fixed_rounds", controller_options={"rounds": 2}),
        round_preparer=RoundPreparer(["round-two"]), checkpoint_root=tmp_path,
    )
    result = stage.execute(["round-one"], ExecutionContext())
    assert result.rounds_completed == 2 and result.payload == "round-two"
    assert len(sorted(tmp_path.rglob("round-*.json"))) == 2


def test_stage_pipeline_stops_before_next_stage_after_cancellation():
    event = Event(); calls = []
    class Runtime:
        def execute(self, *, task, content):
            calls.append(task)
            if task == "first": event.set()
            return TaskCallResult(content + task, True)
        def fingerprint_metadata(self): return {"runtime": "cancel-test-v1"}
    root = SimpleNamespace(taskSetting={}, model_spec_name="test", max_tokens=100)
    pipeline = StagePipelineExecutable([
        {"name": "one", "task": "first"},
        {"name": "two", "task": "second", "input_from": "previous"},
    ])
    with pytest.raises(ExecutionCancelled):
        pipeline.execute("input", ExecutionContext(
            root, Runtime(), cancellation=EventCancellationSignal(event)))
    assert calls == ["first"]
