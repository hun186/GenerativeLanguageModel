from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from czjLLM.reduction.runtime_semantic import SemanticLLMRuntimeAdapter, SemanticRuntimeError


class Tokenizer:
    chunks = None
    def __init__(self, **kwargs): self.kwargs = kwargs
    def tokenize(self, **kwargs): return {"ctxCut": self.chunks or [kwargs["text"]]}


class Generator:
    contexts = []
    def __init__(self, ctx): self.contexts.append(ctx)
    def build(self, content): return f"PROMPT::{self.contexts[-1].task}::{content}"


class Pipeline:
    calls = []
    response = {"ok": True, "output": "answer", "cost": 2}
    def __init__(self, **kwargs):
        self.kwargs = kwargs; self.model_spec = dict(kwargs["model_spec"]); self.calls.append(kwargs)
    def proc(self): return dict(self.response)


def ctx():
    return SimpleNamespace(task="ROOT", model_spec_name="safe", max_tokens=100,
                           model_spec={"model_name": "safe", "base_url": "secret-url", "api_key": "secret"},
                           think_mode=False, PGMSubDir="sub", llm_call_audit_run_id="run",
                           llm_call_audit_path="audit.csv")


def adapter(root, lease):
    return SemanticLLMRuntimeAdapter(ctx=root, tokenizer_factory=Tokenizer,
        prompt_generator_factory=Generator, pipeline_factory=Pipeline, lease_factory=lease)


def test_overlay_prompt_preflight_pipeline_and_lease_without_root_mutation():
    events = []
    @contextmanager
    def lease(c, n):
        events.append(("enter", c, n)); yield 1; events.append(("exit", c, n))
    root = ctx(); result = adapter(root, lease).execute(task="SUMMARY", content="items")
    assert root.task == "ROOT" and Generator.contexts[-1].task == "SUMMARY"
    assert Pipeline.calls[-1]["content"] == "PROMPT::SUMMARY::items"
    assert Pipeline.calls[-1]["OutputSaveFN"] == ""
    assert Pipeline.calls[-1]["audit_run_id"] == "run"
    assert [event[0] for event in events] == ["enter", "exit"]
    assert result.output == "answer" and result.model_name == "safe"
    assert "secret" not in repr(result)


def test_oversized_prompt_fails_before_pipeline_or_lease():
    Tokenizer.chunks = ["one", "two"]
    Pipeline.calls.clear(); leased = []
    @contextmanager
    def lease(*args): leased.append(True); yield 1
    try:
        with pytest.raises(SemanticRuntimeError, match="exceeds one configured token chunk"):
            adapter(ctx(), lease).execute(task="SUMMARY", content="large")
        assert Pipeline.calls == [] and leased == []
    finally:
        Tokenizer.chunks = None


def test_lease_releases_when_pipeline_fails_and_empty_output_fails():
    state = {"in_use": 0}
    @contextmanager
    def lease(*args):
        state["in_use"] += 1
        try: yield 1
        finally: state["in_use"] -= 1
    Pipeline.response = {"ok": False, "output": "", "error": "network"}
    try:
        with pytest.raises(SemanticRuntimeError, match="network"):
            adapter(ctx(), lease).execute(task="SUMMARY", content="x")
        assert state["in_use"] == 0
        Pipeline.response = {"ok": True, "output": "   ", "cost": 0}
        with pytest.raises(SemanticRuntimeError, match="empty"):
            adapter(ctx(), lease).execute(task="SUMMARY", content="x")
        assert state["in_use"] == 0
    finally:
        Pipeline.response = {"ok": True, "output": "answer", "cost": 2}
