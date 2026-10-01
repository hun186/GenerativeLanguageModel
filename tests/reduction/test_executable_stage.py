from __future__ import annotations

from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from types import MappingProxyType
from types import SimpleNamespace
import time

import pytest

from czjLLM.reduction import (
    ExecutableRegistry, ExecutableResult, ExecutionContext, ExecutionError,
    PipelineRefExecutable, ReductionStage, StagePipelineExecutable, TaskCallResult,
    TaskExecutable, TokenizerRoundPreparer, parse_reduction_config,
    parse_reduction_stage_config,
    ReductionStageResult,
)
from czjLLM.reduction.runtime_task import ProductionTaskRuntime
from czjLLM.reduction.execution import _stable_semantics


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


def production_context(*, task_spec=None, model_spec=None, model_spec_name="tokenizer-a"):
    root = SimpleNamespace(
        model_spec_name=model_spec_name, max_tokens=64, think_mode=True,
        taskSetting={"summary": task_spec or {"task": "prompt-a", "InputCutLen": 17}},
        model_spec=model_spec or {"model_name": "model-a"},
    )
    return ExecutionContext(root, ProductionTaskRuntime(root))


def test_task_fingerprint_uses_effective_task_spec_and_raw_task_is_deterministic():
    worker = TaskExecutable("summary")
    first = worker.fingerprint_metadata(production_context(task_spec={"task": "A"}))
    second = worker.fingerprint_metadata(production_context(task_spec={"task": "B"}))
    assert first != second
    raw = TaskExecutable("raw prompt")
    assert raw.fingerprint_metadata(production_context()) == raw.fingerprint_metadata(production_context())


def test_callable_semantics_prefer_source_and_have_stable_fallback(monkeypatch):
    def template_a(content): return "A" + content
    def template_b(content): return "B" + content
    template_a.__qualname__ = template_b.__qualname__ = "logical_template"
    monkeypatch.setattr("czjLLM.reduction.execution.inspect.getsource",
                        lambda fn: "return A" if fn is template_a else "return B")
    assert _stable_semantics(template_a)["callable_source"] == "return A"
    assert _stable_semantics(template_a) != _stable_semantics(template_b)
    monkeypatch.setattr("czjLLM.reduction.execution.inspect.getsource",
                        lambda fn: (_ for _ in ()).throw(OSError()))
    fallback = _stable_semantics(template_a)
    assert set(fallback) == {"callable_module", "callable_qualname"}


@pytest.mark.parametrize("key,value", [
    ("top_k", 40), ("repeat_penalty", 1.2), ("stop", ["END"]),
    ("context_window", 8192),
])
def test_model_semantic_settings_change_task_fingerprint(key, value):
    baseline = TaskExecutable("summary").fingerprint_metadata(production_context())
    changed = TaskExecutable("summary").fingerprint_metadata(
        production_context(model_spec={"model_name": "model-a", key: value})
    )
    assert baseline != changed


def test_model_identity_changes_but_credentials_urls_and_budget_do_not():
    worker = ReductionStage(TaskExecutable("summary"), config())
    base = production_context(model_spec={"model_name": "model-a", "api_key": "one",
                                          "base_url": "https://one.invalid"})
    equivalent = production_context(model_spec={"model_name": "model-a", "api_key": "two",
                                                "base_url": "https://two.invalid"})
    base.runtime_ctx._execution_budget = SimpleNamespace(capacity=1)
    equivalent.runtime_ctx._execution_budget = SimpleNamespace(capacity=99)
    assert worker.execution_fingerprint(base) == worker.execution_fingerprint(equivalent)
    changed = production_context(model_spec_name="tokenizer-b")
    assert worker.execution_fingerprint(base) != worker.execution_fingerprint(changed)


def test_task_input_cut_len_controls_tokenizer_and_fingerprint():
    seen = []
    class Tokenizer:
        def __init__(self, **kwargs): self.max_input_tokens = 3000; seen.append(self)
        def tokenize(self, **kwargs): return {"ctxCut": [kwargs["text"]]}
    class Pipeline:
        def __init__(self, **kwargs): self.model_spec = {"model_name": "safe"}
        def proc(self): return {"ok": True, "output": "ok", "cost": 0}
    @contextmanager
    def lease(*args): yield 1
    contexts = []
    for cut in (11, 22):
        root = SimpleNamespace(model_spec_name="safe", model_spec={"model_name": "safe"},
                               max_tokens=64, think_mode=True,
                               taskSetting={"summary": {"task": "prompt", "InputCutLen": cut}})
        runtime = ProductionTaskRuntime(root, tokenizer_factory=Tokenizer,
                                        pipeline_factory=Pipeline, lease_factory=lease,
                                        renderer=lambda task, content, ctx: content)
        contexts.append(ExecutionContext(root, runtime))
        runtime.execute(task="summary", content="text")
    assert [item.max_input_tokens for item in seen] == [11, 22]
    assert TaskExecutable("summary").fingerprint_metadata(contexts[0]) != \
           TaskExecutable("summary").fingerprint_metadata(contexts[1])


def test_round_preparer_input_cut_len_controls_tokenizer_and_fingerprint():
    seen = []
    class Tokenizer:
        def __init__(self, **kwargs): self.max_input_tokens = 3000; seen.append(self)
        def tokenize(self, **kwargs): return {"ctxCut": [kwargs["text"]]}
    preparer = TokenizerRoundPreparer("summary", tokenizer_factory=Tokenizer)
    contexts = []
    for cut in (31, 32):
        root = SimpleNamespace(model_spec_name="same", max_tokens=64,
                               taskSetting={"summary": {"InputCutLen": cut}})
        context = ExecutionContext(root, Runtime())
        contexts.append(context)
        tuple(preparer.prepare("aggregate", 2, context))
    assert [item.max_input_tokens for item in seen] == [31, 32]
    assert preparer.fingerprint_metadata(contexts[0]) != preparer.fingerprint_metadata(contexts[1])


def test_pipeline_effective_pool_drives_execution_fingerprint_and_explicit_nested_rendering():
    class Tokenizer:
        def __init__(self, **kwargs): self.max_input_tokens = 3000
        def tokenize(self, **kwargs): return {"ctxCut": [kwargs["text"]]}
    class Pipeline:
        outputs = []
        def __init__(self, **kwargs): self.kwargs = kwargs; self.model_spec = {"model_name": "safe"}
        def proc(self): self.outputs.append(self.kwargs["content"]); return {"ok": True, "output": self.kwargs["content"], "cost": 0}
    @contextmanager
    def lease(*args): yield 1
    def renderer(task, content, render_ctx):
        pool = render_ctx.taskSetting
        spec = pool.get(task, task) if isinstance(task, str) else task
        if isinstance(spec, MappingProxyType) or isinstance(spec, dict):
            spec = pool.get(spec.get("task"), spec.get("task", ""))
        return f"{spec}:{content}"
    def make_context(task_setting):
        root = SimpleNamespace(model_spec_name="safe", model_spec={"model_name": "safe"},
                               max_tokens=64, think_mode=True, taskSetting=task_setting)
        runtime = ProductionTaskRuntime(root, tokenizer_factory=Tokenizer,
                                        pipeline_factory=Pipeline, lease_factory=lease,
                                        renderer=renderer)
        return ExecutionContext(root, runtime)
    pipeline = StagePipelineExecutable([{"name": "one", "task_key": "summary", "task": "fallback"}])
    a = make_context({"summary": "A"}); b = make_context({"summary": "B"})
    assert pipeline.fingerprint_metadata(a) != pipeline.fingerprint_metadata(b)
    assert pipeline.execute("text", a).output != pipeline.execute("text", b).output
    explicit = StagePipelineExecutable(
        [{"name": "one", "task_key": "outer", "task": "fallback"}],
        task_setting={"outer": {"task": "inner"}, "inner": "EXPLICIT"},
    )
    result = explicit.execute("text", make_context({"outer": {"task": "wrong"}, "wrong": "ROOT"}))
    assert "EXPLICIT" in result.output and "ROOT" not in result.output


def test_pipeline_ref_preserves_target_audit_namespace():
    pipeline = StagePipelineExecutable([{"name": "one", "task": "A"}])
    registry = ExecutableRegistry({"ok": pipeline})
    result = PipelineRefExecutable("ok").execute("x", ctx(registry=registry))
    assert result.audit["target"]["stage_count"] == 1


class IdentityExecutable:
    executor_type = "identity"
    contract_version = "v1"
    def execute(self, item, context): return ExecutableResult(item, self.executor_type, self.contract_version)
    def fingerprint_metadata(self, context): return {"type": "identity"}


def test_single_pass_stage_preserves_structured_relational_metadata():
    reduction = parse_reduction_config({
        "enabled": True, "profile": "structured_relational", "options": {
            "entity_sets": [{"name": "events", "collection_path": "Event",
                             "id_field": "id", "canonical_prefix": "E"}],
            "references": [],
        },
    })
    result = ReductionStage(IdentityExecutable(), reduction).execute(
        [{"Event": [{"id": "local", "value": "x"}]}], ctx()
    )
    assert result.provenance["reducer"]["id_remap"]
    assert "reducer" in result.audit and "reducer" in result.metrics


def test_executable_construction_detaches_caller_configuration():
    task_source = {"task": "A", "nested": {"value": 1}}
    worker = TaskExecutable(task_source)
    task_source["task"] = "B"; task_source["nested"]["value"] = 2
    assert worker.task["task"] == "A" and worker.task["nested"]["value"] == 1
    stages = [{"name": "route", "task": "route"},
              {"name": "final", "task": "fallback", "route_by": "route",
               "route_map": {"FIN": "A"}, "route_value_mode": "task"}]
    pipeline = StagePipelineExecutable(stages, task_setting={"A": "original"})
    before = pipeline.fingerprint_metadata(ctx())
    stages[1]["route_map"]["FIN"] = "B"
    assert pipeline.fingerprint_metadata(ctx()) == before


def test_reduction_stage_result_detaches_mapping_fields():
    audit = {"a": 1}; provenance = {"p": 2}; metrics = {"m": 3}
    result = ReductionStageResult("x", "concat_text", "single_pass", 1, "done", 1,
                                  audit=audit, provenance=provenance, metrics=metrics)
    audit["later"] = provenance["later"] = metrics["later"] = True
    assert dict(result.audit) == {"a": 1}
    assert dict(result.provenance) == {"p": 2}
    assert dict(result.metrics) == {"m": 3}
