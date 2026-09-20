import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from czjLLM.reduction.runtime_text import (
    TextRoundRuntimeAdapter,
    TextRoundRuntimeError,
)


class FakeTokenizer:
    chunks = ["part-b", "part-a"]

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def tokenize(self, **kwargs):
        return {"ctxCut": list(self.chunks)}


class OverlayLikeContext:
    """Dependency-light double for CtxOverlay's slots and mutable overrides."""

    __slots__ = ("_base", "_ov")

    def __init__(self, base, **overrides):
        object.__setattr__(self, "_base", base)
        object.__setattr__(self, "_ov", dict(overrides))

    def __getattr__(self, name):
        if name in self._ov:
            return self._ov[name]
        return getattr(self._base, name)

    def __setattr__(self, name, value):
        self._ov[name] = value


class RecordingGenerator:
    tasks = []

    def __init__(self, ctx):
        self.ctx = ctx
        self.tasks.append(ctx.task)

    def build(self, content):
        return f"{self.ctx.task}:{content}"


def template_one(content):
    return f"one:{content}"


def template_two(content):
    return f"two:{content}"


def _ctx(**overrides):
    values = dict(
        task="ORIGINAL", model_spec_name="model-v1", model_spec={"model_name": "m", "temperature": 0.2},
        max_tokens=4096, think_mode=False, mock_llm_mode=True, PGMSubDir="",
        removeFinPromptFile=True, mp_for_all_call=True,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _successful_dispatch(seen):
    def dispatch(items, ctx, task_override=None):
        root = Path(items[0])
        seen.extend((p.name, p.read_text(encoding="utf-8")) for p in sorted((root / "TODO").glob("*.txt")))
        for prompt in sorted((root / "TODO").glob("*.txt"), reverse=True):
            (root / "Success" / prompt.name).write_text(f"out-{prompt.stem}", encoding="utf-8")
            prompt.unlink()
    return dispatch


def _successful_dispatch_recording_task(seen):
    dispatch_success = _successful_dispatch([])

    def dispatch(items, ctx, **kwargs):
        seen.append(ctx.task)
        dispatch_success(items, ctx, **kwargs)

    return dispatch


def test_round_reslices_renders_and_collects_in_stable_lexical_order(tmp_path):
    RecordingGenerator.tasks.clear()
    seen = []
    ctx = _ctx()
    adapter = TextRoundRuntimeAdapter(
        ctx=ctx, item_workspace=tmp_path, round_task="ROUND TASK",
        tokenizer_factory=FakeTokenizer, prompt_generator_factory=RecordingGenerator,
        llm_dispatch=_successful_dispatch(seen),
    )

    assert adapter.next_round_items("aggregate", 2) == ["out-0000\n", "out-0001\n"]
    assert seen == [("0000.txt", "ROUND TASK:part-b"), ("0001.txt", "ROUND TASK:part-a")]
    assert RecordingGenerator.tasks == ["ROUND TASK"]
    assert ctx.task == "ORIGINAL"


def test_output_newline_preparation_preserves_existing_content(tmp_path):
    def dispatch(items, ctx, task_override=None):
        root = Path(items[0])
        outputs = ["foo", "bar\n"]
        for prompt, output in zip(sorted((root / "TODO").glob("*.txt")), outputs):
            (root / "Success" / prompt.name).write_text(output, encoding="utf-8")
            prompt.unlink()

    adapter = TextRoundRuntimeAdapter(
        ctx=_ctx(), item_workspace=tmp_path, round_task="ROUND",
        tokenizer_factory=FakeTokenizer, prompt_generator_factory=RecordingGenerator,
        llm_dispatch=dispatch,
    )

    assert adapter.next_round_items("aggregate", 2) == ["foo\n", "bar\n"]


def test_overlay_like_context_is_not_mutated_by_successful_round(tmp_path):
    base = _ctx(task="BASE")
    overlay = OverlayLikeContext(base, task="ROW TASK")
    original_overrides = dict(overlay._ov)
    seen_tasks = []

    def dispatch(items, ctx, task_override=None):
        seen_tasks.append(ctx.task)
        _successful_dispatch([])(items, ctx, task_override=task_override)

    adapter = TextRoundRuntimeAdapter(
        ctx=overlay, item_workspace=tmp_path, round_task="ROUND TASK",
        tokenizer_factory=FakeTokenizer, prompt_generator_factory=RecordingGenerator,
        llm_dispatch=dispatch,
    )

    adapter.next_round_items("aggregate", 2)
    assert seen_tasks == ["ROUND TASK"]
    assert overlay.task == "ROW TASK"
    assert overlay._ov == original_overrides
    assert base.task == "BASE"


@pytest.mark.parametrize("failure_stage", ["tokenizer", "prompt", "dispatch"])
def test_original_task_is_unchanged_after_round_failure(tmp_path, failure_stage):
    ctx = _ctx(task="ORIGINAL")

    class FailingTokenizer(FakeTokenizer):
        def tokenize(self, **kwargs):
            raise RuntimeError("tokenizer failed")

    class FailingGenerator(RecordingGenerator):
        def build(self, content):
            raise RuntimeError("prompt failed")

    def failing_dispatch(*args, **kwargs):
        raise RuntimeError("dispatch failed")

    adapter = TextRoundRuntimeAdapter(
        ctx=ctx,
        item_workspace=tmp_path,
        round_task="ROUND",
        tokenizer_factory=FailingTokenizer if failure_stage == "tokenizer" else FakeTokenizer,
        prompt_generator_factory=(
            FailingGenerator if failure_stage == "prompt" else RecordingGenerator
        ),
        llm_dispatch=(
            failing_dispatch if failure_stage == "dispatch" else _successful_dispatch([])
        ),
    )

    with pytest.raises(TextRoundRuntimeError):
        adapter.next_round_items("aggregate", 2)
    assert ctx.task == "ORIGINAL"


def test_adapters_with_same_base_context_do_not_cross_contaminate(tmp_path):
    ctx = _ctx(task="ORIGINAL")
    seen = []
    first = TextRoundRuntimeAdapter(
        ctx=ctx, item_workspace=tmp_path / "first", round_task="FIRST",
        tokenizer_factory=FakeTokenizer, prompt_generator_factory=RecordingGenerator,
        llm_dispatch=_successful_dispatch_recording_task(seen),
    )
    second = TextRoundRuntimeAdapter(
        ctx=ctx, item_workspace=tmp_path / "second", round_task="SECOND",
        tokenizer_factory=FakeTokenizer, prompt_generator_factory=RecordingGenerator,
        llm_dispatch=_successful_dispatch_recording_task(seen),
    )

    first.next_round_items("aggregate", 2)
    second.next_round_items("aggregate", 2)
    assert seen == ["FIRST", "SECOND"]
    assert ctx.task == "ORIGINAL"


def test_incomplete_map_fails_and_stale_uncommitted_workspace_is_rebuilt(tmp_path):
    stale = tmp_path / ".reduction/runtime/round-0002"
    (stale / "TODO").mkdir(parents=True)
    (stale / "TODO/stale.txt").write_text("stale", encoding="utf-8")
    adapter = TextRoundRuntimeAdapter(
        ctx=_ctx(), item_workspace=tmp_path, round_task="ROUND",
        tokenizer_factory=FakeTokenizer, prompt_generator_factory=RecordingGenerator,
        llm_dispatch=lambda *args, **kwargs: None,
    )
    with pytest.raises(TextRoundRuntimeError, match="TODO remains"):
        adapter.next_round_items("aggregate", 2)
    assert not (stale / "TODO/stale.txt").exists()


def test_fingerprint_is_deterministic_sensitive_and_secret_free(tmp_path):
    base = _ctx(model_spec={
        "model_name": "m", "temperature": 0.2, "api_key": "TOP-SECRET",
        "base_url": "https://secret.invalid/token",
    })
    same = _ctx(model_spec=dict(base.model_spec))
    first = TextRoundRuntimeAdapter(ctx=base, item_workspace=tmp_path, round_task="raw task")
    second = TextRoundRuntimeAdapter(ctx=same, item_workspace=tmp_path, round_task="raw task")
    assert first.execution_fingerprint() == second.execution_fingerprint()
    assert first.execution_fingerprint() != TextRoundRuntimeAdapter(
        ctx=same, item_workspace=tmp_path, round_task="changed task"
    ).execution_fingerprint()
    assert first.execution_fingerprint() != TextRoundRuntimeAdapter(
        ctx=_ctx(model_spec={"model_name": "m", "temperature": 0.9}),
        item_workspace=tmp_path, round_task="raw task",
    ).execution_fingerprint()
    metadata = repr(first.fingerprint_metadata())
    assert "TOP-SECRET" not in metadata
    assert "secret.invalid" not in metadata
    assert "api_key" not in metadata
    credential_change = _ctx(model_spec={
        "model_name": "m", "temperature": 0.2, "api_key": "OTHER-SECRET",
        "base_url": "https://other.invalid",
    })
    assert first.execution_fingerprint() == TextRoundRuntimeAdapter(
        ctx=credential_change, item_workspace=tmp_path, round_task="raw task"
    ).execution_fingerprint()


def test_fingerprint_tracks_shared_production_task_pool_semantics(tmp_path):
    # LLMJobConfig exposes the same repository task pool used by the production
    # PromptGenerator/TokenizerWrapper. Keep that invariant explicit here rather
    # than implying that the adapter injects a separate renderer task registry.
    task_pool = {"REGISTERED": {"template": template_one, "InputCutLen": 100}}
    ctx = _ctx(taskSetting=task_pool)
    one = TextRoundRuntimeAdapter(ctx=ctx, item_workspace=tmp_path, round_task="REGISTERED")
    one_fingerprint = one.execution_fingerprint()

    task_pool["REGISTERED"] = {"template": template_two, "InputCutLen": 100}
    assert one_fingerprint != one.execution_fingerprint()
    task_pool["REGISTERED"] = {"template": template_one, "InputCutLen": 200}
    assert one_fingerprint != one.execution_fingerprint()


def test_runtime_source_has_no_recursive_orchestration_calls():
    source = inspect.getsource(TextRoundRuntimeAdapter)
    assert "combine_api_finished_item" not in source
    assert "process_prompt_and_merge" not in source
