from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from czjLLM.reduction import (
    ExecutableRegistry, ExecutionContext, ExecutionError, ExecutionNestingState,
    IdentityInputPreparer, PipelineRefExecutable, ReductionStage,
    ReductionStageExecutable, StagePipelineExecutable, TaskCallResult, TaskExecutable,
    TokenizerInputPreparer, TokenizerRoundPreparer, parse_reduction_config,
    parse_reduction_stage_executable_config,
)
from czjLLM.reduction.config import ReductionConfigError


class Runtime:
    def __init__(self, pool=None):
        self.pool = pool or {}
        self.calls = []

    def execute(self, *, task, content):
        self.calls.append((task, content))
        return TaskCallResult(f"<{content}>", True, "safe", 0)

    def fingerprint_metadata(self):
        return {"runtime": "test-v1"}

    def effective_input_cut_len(self, task):
        current = self.pool.get(task, {})
        while isinstance(current, dict):
            if type(current.get("InputCutLen")) is int:
                return current["InputCutLen"]
            current = self.pool.get(current.get("task"))
        return 3000


def context(*, registry=None, runtime=None, nesting=None, pool=None):
    pool = pool or {"summary": {"InputCutLen": 7}}
    root = SimpleNamespace(model_spec_name="model-a", max_tokens=64, taskSetting=pool)
    return ExecutionContext(root, runtime or Runtime(pool), registry, {},
                            nesting or ExecutionNestingState())


def reduction(controller="single_pass", **extra):
    raw = {"enabled": True, "profile": "concat_text", "controller": controller, **extra}
    if controller != "single_pass":
        raw["runtime"] = {"round_task": "compat"}
    return parse_reduction_config(raw)


def nested(worker=None, *, preparer=None, parallelism=1, checkpoint_root=None):
    return ReductionStageExecutable(
        ReductionStage(worker or TaskExecutable("summary"), reduction(), parallelism,
                       checkpoint_root=checkpoint_root),
        preparer or IdentityInputPreparer(),
    )


def ordinary(task="summary"):
    return StagePipelineExecutable([{"name": "one", "task": task}])


def test_nesting_state_defaults_bounds_and_immutability():
    state = ExecutionNestingState()
    assert (state.nested_reduction_depth, state.max_nested_reduction_depth) == (0, 1)
    assert (state.pipeline_ref_stack, state.max_pipeline_ref_depth) == ((), 4)
    with pytest.raises(FrozenInstanceError):
        state.nested_reduction_depth = 1
    with pytest.raises(ValueError): ExecutionNestingState(max_nested_reduction_depth=2)
    with pytest.raises(ValueError): ExecutionNestingState(max_pipeline_ref_depth=5)
    disabled = ExecutionNestingState(max_nested_reduction_depth=0)
    with pytest.raises(ExecutionError, match="max_nested_reduction_depth"):
        disabled.enter_nested_reduction()
    child = state.enter_nested_reduction()
    pushed = state.push_pipeline_ref("A")
    assert state.nested_reduction_depth == 0 and child.nested_reduction_depth == 1
    assert state.pipeline_ref_stack == () and pushed.pipeline_ref_stack == ("A",)


def test_direct_and_chained_refs_execute_and_preserve_nested_audit():
    registry = ExecutableRegistry({"pipe": ordinary(), "alias": PipelineRefExecutable("pipe")})
    direct = PipelineRefExecutable("pipe").execute("x", context(registry=registry))
    chained = PipelineRefExecutable("alias").execute("x", context(registry=registry))
    assert direct.output == chained.output == "<x>"
    assert chained.audit["target"]["pipeline_ref"] == "pipe"


def test_ref_to_nested_reduction_and_sibling_stack_isolation():
    registry = ExecutableRegistry({"nested": nested()})
    root = context(registry=registry)
    ref = PipelineRefExecutable("nested")
    assert ref.execute("a", root).output == "<a>"
    assert ref.execute("b", root).output == "<b>"
    assert root.nesting.pipeline_ref_stack == ()


@pytest.mark.parametrize("entries,start,path", [
    ({"A": PipelineRefExecutable("A")}, "A", "A -> A"),
    ({"A": PipelineRefExecutable("B"), "B": PipelineRefExecutable("A")}, "A", "A -> B -> A"),
    ({"A": PipelineRefExecutable("B"), "B": PipelineRefExecutable("C"),
      "C": PipelineRefExecutable("A")}, "A", "A -> B -> C -> A"),
])
def test_ref_cycles_fail_for_execution_and_fingerprint(entries, start, path):
    ctx = context(registry=ExecutableRegistry(entries))
    for operation in (lambda: PipelineRefExecutable(start).execute("x", ctx),
                      lambda: PipelineRefExecutable(start).fingerprint_metadata(ctx)):
        with pytest.raises(ExecutionError, match=path): operation()


def test_four_refs_allowed_fifth_rejected_execution_and_fingerprint():
    allowed = {"A": PipelineRefExecutable("B"), "B": PipelineRefExecutable("C"),
               "C": PipelineRefExecutable("D"), "D": ordinary()}
    ctx = context(registry=ExecutableRegistry(allowed))
    assert PipelineRefExecutable("A").execute("x", ctx).output == "<x>"
    overflow = {"A": PipelineRefExecutable("B"), "B": PipelineRefExecutable("C"),
                "C": PipelineRefExecutable("D"), "D": PipelineRefExecutable("E"),
                "E": ordinary()}
    ctx = context(registry=ExecutableRegistry(overflow))
    for operation in (lambda: PipelineRefExecutable("A").execute("x", ctx),
                      lambda: PipelineRefExecutable("A").fingerprint_metadata(ctx)):
        with pytest.raises(ExecutionError, match="max_pipeline_ref_depth"): operation()


def test_unknown_and_unsupported_ref_targets_fail_closed():
    with pytest.raises(ExecutionError, match="unknown pipeline ref"):
        PipelineRefExecutable("missing").execute("x", context(registry=ExecutableRegistry()))
    registry = ExecutableRegistry({"task": TaskExecutable("summary")})
    with pytest.raises(ExecutionError, match="PipelineRef target"):
        PipelineRefExecutable("task").execute("x", context(registry=registry))


def test_one_nested_depth_succeeds_and_disabled_depth_rejects_both_paths():
    executable = nested()
    assert executable.execute("x", context()).audit["nested_reduction_depth"] == 1
    disabled = context(nesting=ExecutionNestingState(max_nested_reduction_depth=0))
    for operation in (lambda: executable.execute("x", disabled),
                      lambda: executable.fingerprint_metadata(disabled)):
        with pytest.raises(ExecutionError, match="max_nested_reduction_depth"): operation()


def test_second_nested_stage_rejected_for_execution_and_fingerprint():
    inner = nested()
    registry = ExecutableRegistry({"inner": inner})
    outer = nested(PipelineRefExecutable("inner"))
    ctx = context(registry=registry)
    for operation in (lambda: outer.execute("x", ctx), lambda: outer.fingerprint_metadata(ctx)):
        with pytest.raises(ExecutionError, match="max_nested_reduction_depth"): operation()


def test_identity_preparer_preserves_one_item_and_has_stable_identity():
    preparer = IdentityInputPreparer()
    ctx = context()
    item = {"safe": 1}
    assert tuple(preparer.prepare(item, ctx)) == (item,)
    assert preparer.fingerprint_metadata(ctx) == preparer.fingerprint_metadata(ctx)


def test_tokenizer_input_validation_order_boundary_and_no_task_call():
    seen = []
    class Tokenizer:
        def __init__(self, **kwargs): seen.append(("init", kwargs)); self.max_input_tokens = None
        def tokenize(self, **kwargs):
            seen.append(("tokenize", self.max_input_tokens, kwargs)); return {"ctxCut": ["one", "two"]}
    runtime = Runtime({"alias": {"task": "real"}, "real": {"InputCutLen": 11}})
    ctx = context(runtime=runtime, pool=runtime.pool)
    preparer = TokenizerInputPreparer("alias", tokenizer_factory=Tokenizer)
    assert tuple(preparer.prepare("document", ctx)) == ("one", "two")
    assert seen[0][1] == {"model_name": "model-a", "task": "alias", "max_tokens": 64}
    assert seen[1][1] == 11 and runtime.calls == []
    for invalid in (None, 1, "", "  "):
        with pytest.raises(ExecutionError): tuple(preparer.prepare(invalid, ctx))


def test_input_and_round_preparers_share_effective_nested_boundary_and_fingerprint():
    values = []
    class Tokenizer:
        def __init__(self, **kwargs): self.max_input_tokens = None
        def tokenize(self, **kwargs): values.append(self.max_input_tokens); return {"ctxCut": [kwargs["text"]]}
    pool = {"alias": {"task": "real"}, "real": {"InputCutLen": 13}}
    ctx = context(pool=pool, runtime=Runtime(pool))
    initial = TokenizerInputPreparer("alias", tokenizer_factory=Tokenizer)
    rounds = TokenizerRoundPreparer("alias", tokenizer_factory=Tokenizer)
    tuple(initial.prepare("x", ctx)); tuple(rounds.prepare("x", 2, ctx))
    assert values == [13, 13]
    changed_pool = {"alias": {"task": "real"}, "real": {"InputCutLen": 14}}
    changed = context(pool=changed_pool, runtime=Runtime(changed_pool))
    assert initial.fingerprint_metadata(ctx) != initial.fingerprint_metadata(changed)
    assert rounds.fingerprint_metadata(ctx) != rounds.fingerprint_metadata(changed)


def test_stage_fingerprint_covers_semantics_not_operational_values(tmp_path):
    ctx = context()
    base = ReductionStage(TaskExecutable("a"), reduction(), 1, checkpoint_root=tmp_path / "a")
    operational = ReductionStage(TaskExecutable("a"), reduction(), 9, checkpoint_root=tmp_path / "b")
    assert base.execution_fingerprint(ctx) == operational.execution_fingerprint(ctx)
    assert base.execution_fingerprint(ctx) != ReductionStage(
        TaskExecutable("b"), reduction(), 1).execution_fingerprint(ctx)
    option_a = parse_reduction_config({"enabled": True, "profile": "legacy_json_deep_merge",
                                       "options": {"conflict_policy": "prefer_left"}})
    option_b = parse_reduction_config({"enabled": True, "profile": "legacy_json_deep_merge",
                                       "options": {"conflict_policy": "prefer_right"}})
    assert ReductionStage(TaskExecutable("a"), option_a).execution_fingerprint(ctx) != \
        ReductionStage(TaskExecutable("a"), option_b).execution_fingerprint(ctx)
    ctx.runtime_ctx._execution_budget = SimpleNamespace(capacity=99)
    assert base.execution_fingerprint(ctx) == operational.execution_fingerprint(ctx)


def test_nested_fingerprint_covers_pipeline_controller_round_and_input_semantics():
    registry_a = ExecutableRegistry({"pipe": ordinary("a")})
    registry_b = ExecutableRegistry({"pipe": ordinary("b")})
    executable = nested(PipelineRefExecutable("pipe"))
    assert executable.fingerprint_metadata(context(registry=registry_a)) != \
        executable.fingerprint_metadata(context(registry=registry_b))
    fixed_a = reduction("fixed_rounds", controller_options={"rounds": 2})
    fixed_b = reduction("fixed_rounds", controller_options={"rounds": 3})
    one = ReductionStageExecutable(ReductionStage(TaskExecutable("a"), fixed_a,
                                                   round_preparer=TokenizerRoundPreparer("a")),
                                   IdentityInputPreparer())
    two = ReductionStageExecutable(ReductionStage(TaskExecutable("a"), fixed_b,
                                                   round_preparer=TokenizerRoundPreparer("b")),
                                   TokenizerInputPreparer("a", tokenizer_factory=lambda **_: None))
    assert one.fingerprint_metadata(context()) != two.fingerprint_metadata(context())


def test_nested_semantic_reducers_rejected_but_top_level_remains_constructible():
    direct = parse_reduction_config({"enabled": True, "profile": "semantic_llm",
                                     "options": {"task": "summary"}})
    composite = parse_reduction_config({"enabled": True, "profile": "composite", "options": {
        "steps": [{"profile": "semantic_llm", "options": {"task": "summary"}}]}})
    top_level = ReductionStage(TaskExecutable("summary"), direct)
    assert top_level.reduction.requires_semantic_runtime()
    for config in (direct, composite):
        with pytest.raises(ValueError, match="semantic reducers"):
            ReductionStageExecutable(ReductionStage(TaskExecutable("summary"), config),
                                     IdentityInputPreparer())


def test_nested_metadata_is_namespaced_and_excludes_payload():
    payload = "PRIVATE-PAYLOAD"
    result = nested().execute(payload, context())
    assert result.audit["stage"] and result.metrics["stage"]
    assert "stage" in result.provenance
    assert payload not in repr(result.audit)


def test_strict_nested_parser_and_semantic_rejection():
    raw = {"type": "reduction_stage", "input_preparer": {"type": "identity"}, "stage": {
        "worker": {"type": "task", "task": "summary"},
        "reduction": {"enabled": True, "profile": "concat_text"}}}
    assert isinstance(parse_reduction_stage_executable_config(raw), ReductionStageExecutable)
    for bad in ({**raw, "extra": True}, {**raw, "type": "other"}):
        with pytest.raises(ReductionConfigError): parse_reduction_stage_executable_config(bad)
    semantic = {**raw, "stage": {**raw["stage"], "reduction": {
        "enabled": True, "profile": "semantic_llm", "options": {"task": "summary"}}}}
    with pytest.raises(ReductionConfigError, match="semantic reducers"):
        parse_reduction_stage_executable_config(semantic)


def test_orchestration_classes_do_not_acquire_leaf_leases():
    for path in ("czjLLM/reduction/nested_execution.py", "czjLLM/reduction/executable_pipeline.py",
                 "czjLLM/reduction/stage.py"):
        source = Path(path).read_text(encoding="utf-8")
        assert "lease_execution_workers" not in source
