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


def test_round_reslices_renders_and_collects_in_stable_lexical_order(tmp_path):
    RecordingGenerator.tasks.clear()
    seen = []
    ctx = _ctx()
    adapter = TextRoundRuntimeAdapter(
        ctx=ctx, item_workspace=tmp_path, round_task="ROUND TASK",
        tokenizer_factory=FakeTokenizer, prompt_generator_factory=RecordingGenerator,
        llm_dispatch=_successful_dispatch(seen),
    )

    assert adapter.next_round_items("aggregate", 2) == ["out-0000", "out-0001"]
    assert seen == [("0000.txt", "ROUND TASK:part-b"), ("0001.txt", "ROUND TASK:part-a")]
    assert RecordingGenerator.tasks == ["ROUND TASK"]
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


def test_fingerprint_tracks_registered_template_and_tokenizer_cut_semantics(tmp_path):
    ctx_one = _ctx(taskSetting={"REGISTERED": {"template": template_one, "InputCutLen": 100}})
    ctx_two = _ctx(taskSetting={"REGISTERED": {"template": template_two, "InputCutLen": 100}})
    ctx_cut = _ctx(taskSetting={"REGISTERED": {"template": template_one, "InputCutLen": 200}})

    one = TextRoundRuntimeAdapter(ctx=ctx_one, item_workspace=tmp_path, round_task="REGISTERED")
    two = TextRoundRuntimeAdapter(ctx=ctx_two, item_workspace=tmp_path, round_task="REGISTERED")
    cut = TextRoundRuntimeAdapter(ctx=ctx_cut, item_workspace=tmp_path, round_task="REGISTERED")
    assert one.execution_fingerprint() != two.execution_fingerprint()
    assert one.execution_fingerprint() != cut.execution_fingerprint()


def test_runtime_source_has_no_recursive_orchestration_calls():
    source = inspect.getsource(TextRoundRuntimeAdapter)
    assert "combine_api_finished_item" not in source
    assert "process_prompt_and_merge" not in source
