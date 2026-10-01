from __future__ import annotations

from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
import time

import pytest

from czjLLM.reduction import (
    ExecutableRegistry, ExecutableResult, ExecutionContext, ExecutionError,
    PipelineRefExecutable, ReductionStage, StagePipelineExecutable, TaskCallResult,
    TaskExecutable, TokenizerRoundPreparer, parse_reduction_config,
    parse_reduction_stage_config,
)
from czjLLM.reduction.runtime_task import ProductionTaskRuntime


class Runtime:
    def __init__(self, fn=lambda task, content: content.upper()): self.fn = fn
    def execute(self, *, task, content):
        value = self.fn(task, content)
        return value if isinstance(value, TaskCallResult) else TaskCallResult(value, True, "safe", 1.0)
    def fingerprint_metadata(self): return {"runtime": "test-v1"}


def ctx(runtime=None, registry=None):
    root = SimpleNamespace(model_spec_name="test", max_tokens=64)
    return ExecutionContext(root, runtime or Runtime(), registry)


def config(controller="single_pass", **options):
    raw = {"enabled": True, "profile": "concat_text", "controller": controller}
    raw.update(options)
    if controller != "single_pass": raw["runtime"] = {"round_task": "legacy-placeholder"}
    return parse_reduction_config(raw)


def test_executable_result_is_frozen_and_has_distinct_contract():
    source = {"safe": 1}
    result = ExecutableResult("x", "test", "v1", audit=source)
    source["later"] = 2
    with pytest.raises(FrozenInstanceError): result.output = "y"
    with pytest.raises(TypeError): result.audit["mutate"] = True
    assert result.output == "x" and dict(result.audit) == {"safe": 1}


@pytest.mark.parametrize("item", [None, 1, {}])
def test_task_executable_rejects_non_text(item):
    with pytest.raises(ExecutionError): TaskExecutable("task").execute(item, ctx())


def test_task_executable_rejects_missing_failed_and_blank_runtime():
    with pytest.raises(ExecutionError): TaskExecutable("t").execute("x", ExecutionContext())
    for result in (TaskCallResult("x", False), TaskCallResult(" ", True)):
        with pytest.raises(ExecutionError):
            TaskExecutable("t").execute("x", ctx(Runtime(lambda *_: result)))


def test_task_audit_is_bounded_and_contains_no_input_or_task():
    result = TaskExecutable("secret prompt").execute("private content", ctx())
    assert "secret prompt" not in repr(result.audit)
    assert "private content" not in repr(result.audit)


def test_stage_pipeline_reuses_previous_input_and_returns_nonpersisted_final():
    seen = []
    runtime = Runtime(lambda task, content: seen.append((task, content)) or f"{task}:{content}")
    pipeline = StagePipelineExecutable([
        {"name": "one", "task": "A", "persist_output": "never"},
        {"name": "two", "task": "B", "input_from": "previous", "persist_output": "never"},
    ])
    result = pipeline.execute("input", ctx(runtime))
    assert seen == [("A", "input"), ("B", "A:input")]
    assert result.output == "B:A:input"


def test_stage_pipeline_inherits_route_map():
    pipeline = StagePipelineExecutable([
        {"name": "route", "task": "route"},
        {"name": "final", "task": "fallback", "route_by": "route",
         "route_map": {"FIN": "summary"}, "route_value_mode": "task"},
    ])
    runtime = Runtime(lambda task, content: "FIN" if task == "route" else f"done:{task}")
    assert pipeline.execute("input", ctx(runtime)).output == "done:summary"


def test_pipeline_ref_is_local_and_rejects_unknown_or_nested_target():
    pipeline = StagePipelineExecutable([{"name": "one", "task": "A"}])
    registry = ExecutableRegistry({"ok": pipeline})
    assert PipelineRefExecutable("ok").execute("x", ctx(registry=registry)).output == "X"
    with pytest.raises(ExecutionError): PipelineRefExecutable("missing").execute("x", ctx(registry=registry))
    nested = ExecutableRegistry({"bad": PipelineRefExecutable("ok")})
    with pytest.raises(ExecutionError): PipelineRefExecutable("bad").execute("x", ctx(registry=nested))
    with pytest.raises(ExecutionError): PipelineRefExecutable("ok").execute("x", ctx(registry=ExecutableRegistry()))


def test_reduction_stage_materializes_once_preserves_parallel_order_and_fails_closed():
    consumed = []
    def items():
        for value in ("a", "b", "c"):
            consumed.append(value); yield value
    runtime = Runtime(lambda task, content: (time.sleep({"a": .03, "b": .02, "c": .01}[content]) or content))
    result = ReductionStage(TaskExecutable("t"), config(), worker_parallelism=3).execute(items(), ctx(runtime))
    assert consumed == ["a", "b", "c"] and result.payload == "abc" and result.worker_execution_count == 3
    bad = Runtime(lambda task, content: TaskCallResult("", False))
    with pytest.raises(ExecutionError): ReductionStage(TaskExecutable("t"), config()).execute(["a"], ctx(bad))


class Preparer:
    def __init__(self): self.seen = []
    def prepare(self, payload, round_index, context): self.seen.append((payload, round_index)); return [payload]
    def fingerprint_metadata(self, context): return {"preparer": "v1"}


def test_fixed_round_stage_runs_preparer_then_worker_without_parent_lease():
    preparer = Preparer()
    stage = ReductionStage(TaskExecutable("t"), config("fixed_rounds", controller_options={"rounds": 2}),
                           worker_parallelism=2, round_preparer=preparer)
    result = stage.execute(["a", "b"], ctx(Runtime(lambda task, content: f"[{content}]")))
    assert result.rounds_completed == 2 and result.worker_execution_count == 3
    assert preparer.seen == [("[a][b]", 2)]


def test_tokenizer_round_preparer_validates_and_preserves_order():
    class Tokenizer:
        def __init__(self, **kwargs): pass
        def tokenize(self, **kwargs): return {"ctxCut": ["a", "b"]}
    preparer = TokenizerRoundPreparer("summary", tokenizer_factory=Tokenizer)
    assert tuple(preparer.prepare("aggregate", 2, ctx())) == ("a", "b")
    with pytest.raises(ExecutionError): tuple(preparer.prepare("", 2, ctx()))
    with pytest.raises(ExecutionError): tuple(preparer.prepare("x", 1, ctx()))


def test_execution_fingerprint_changes_with_task_not_budget_capacity():
    context = ctx()
    one = ReductionStage(TaskExecutable("a"), config()).execution_fingerprint(context)
    two = ReductionStage(TaskExecutable("b"), config()).execution_fingerprint(context)
    context.runtime_ctx._execution_budget = SimpleNamespace(capacity=999)
    assert one != two
    assert one == ReductionStage(TaskExecutable("a"), config()).execution_fingerprint(context)


def test_production_runtime_one_chunk_lease_and_include_think_cleanup():
    events = []
    class Tokenizer:
        def __init__(self, **kwargs): events.append(("tokenizer", kwargs))
        def tokenize(self, **kwargs): events.append(("tokenize", kwargs["text"])); return {"ctxCut": [kwargs["text"]]}
    class Pipeline:
        def __init__(self, **kwargs): events.append(("pipeline", kwargs)); self.model_spec = {"model_name": "safe"}
        def proc(self): events.append(("proc",)); return {"ok": True, "output": " raw output ", "cost": 2}
    @contextmanager
    def lease(_ctx, requested):
        events.append(("lease-enter", requested)); yield 1; events.append(("lease-exit", requested))
    root = SimpleNamespace(model_spec_name="safe", model_spec={"model_name": "safe", "api_key": "secret",
                                                               "base_url": "https://private.invalid"},
                           max_tokens=64, think_mode=True)
    runtime = ProductionTaskRuntime(root, tokenizer_factory=Tokenizer, pipeline_factory=Pipeline,
                                    lease_factory=lease,
                                    renderer=lambda task, content, render_ctx: f"think={render_ctx.think_mode}:{task}:{content}")
    result = runtime.execute(task="summary", content="text")
    pipeline_kwargs = next(value for kind, value in events if kind == "pipeline")
    assert pipeline_kwargs["include_think"] is False and result.output == " raw output "
    assert events[-3:] == [("lease-enter", 1), ("proc",), ("lease-exit", 1)]
    assert "secret" not in repr(runtime.fingerprint_metadata())
    assert "private.invalid" not in repr(runtime.fingerprint_metadata())


def test_production_runtime_oversized_preflight_fails_before_pipeline():
    class Tokenizer:
        def __init__(self, **kwargs): pass
        def tokenize(self, **kwargs): return {"ctxCut": ["one", "two"]}
    called = []
    runtime = ProductionTaskRuntime(
        SimpleNamespace(model_spec_name="safe", model_spec={"model_name": "safe"}, max_tokens=64),
        tokenizer_factory=Tokenizer, pipeline_factory=lambda **kwargs: called.append(kwargs),
        renderer=lambda task, content, ctx: content,
    )
    with pytest.raises(RuntimeError, match="one configured token chunk"):
        runtime.execute(task="summary", content="oversized")
    assert called == []


def test_strict_reduction_stage_parser_does_not_require_legacy_round_task():
    parsed = parse_reduction_stage_config({
        "worker": {"type": "pipeline_ref", "ref": "summary"},
        "worker_parallelism": 2,
        "reduction": {"enabled": True, "profile": "concat_text", "controller": "fixed_rounds",
                      "controller_options": {"rounds": 2}},
        "round_preparer": {"type": "tokenizer", "task": "summary"},
    })
    assert parsed.worker.ref == "summary" and parsed.reduction.runtime == {}
    with pytest.raises(ValueError):
        parse_reduction_stage_config({"worker": {"type": "task", "task": " x "},
                                      "reduction": {"enabled": True, "profile": "concat_text"}})
