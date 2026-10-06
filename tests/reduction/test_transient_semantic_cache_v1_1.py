from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import threading
import time
from types import SimpleNamespace

import pytest

from czjLLM.reduction.runtime_semantic import SemanticLLMRuntimeAdapter
from czjLLM.reduction.transient_cache import (
    ReductionTransientCachePolicy,
    RunScopedSemanticCache,
    parse_reduction_transient_cache_policy,
    ensure_run_scoped_semantic_cache,
    project_reduction_transient_cache_policy,
    semantic_call_cache_key,
)
from czjLLM.reduction.reducers.semantic import SemanticCallResult


class Tokenizer:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def tokenize(self, **kwargs):
        return {"ctxCut": [kwargs["text"]]}


class Generator:
    def __init__(self, ctx):
        self.ctx = ctx

    def build(self, content):
        return f"PROMPT::{self.ctx.task}::{content}"


class Pipeline:
    calls = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.model_spec = dict(kwargs["model_spec"])
        self.calls.append(kwargs)

    def proc(self):
        return {"ok": True, "output": "answer", "cost": 2}


@contextmanager
def lease(*_args):
    yield 1


def _ctx(**changes):
    values = dict(
        task="ROOT",
        taskSetting={"ROOT": {"task": "root"}},
        model_spec_name="safe-profile",
        max_tokens=100,
        model_spec={
            "model_name": "safe-model",
            "temperature": 0.1,
            "api_key": "secret-a",
            "base_url": "https://private-a",
        },
        think_mode=False,
        PGMSubDir="sub",
        llm_call_audit_run_id="run",
        llm_call_audit_path="audit.csv",
        reduction_transient_cache=ReductionTransientCachePolicy(enabled=True),
    )
    values.update(changes)
    return SimpleNamespace(**values)


def _adapter(root, pipeline_factory=Pipeline):
    return SemanticLLMRuntimeAdapter(
        ctx=root,
        tokenizer_factory=Tokenizer,
        prompt_generator_factory=Generator,
        pipeline_factory=pipeline_factory,
        lease_factory=lease,
    )


def test_policy_defaults_strict_validation_and_root_projection():
    assert parse_reduction_transient_cache_policy(None) == ReductionTransientCachePolicy()
    assert not ReductionTransientCachePolicy().enabled
    with pytest.raises(ValueError, match="unknown"):
        parse_reduction_transient_cache_policy({"surprise": True})
    with pytest.raises(TypeError, match="bool"):
        parse_reduction_transient_cache_policy({"enabled": 1})
    with pytest.raises(ValueError, match="positive integer"):
        parse_reduction_transient_cache_policy({"max_entries": 0})
    with pytest.raises(ValueError, match="<="):
        parse_reduction_transient_cache_policy({
            "max_output_characters": 11,
            "max_total_output_characters": 10,
        })

    root = SimpleNamespace()
    project_reduction_transient_cache_policy(
        root,
        lambda key, default=None: {
            "reduction_transient_cache": {"enabled": True, "max_entries": 7}
        }.get(key, default),
    )
    assert root.reduction_transient_cache == ReductionTransientCachePolicy(
        enabled=True, max_entries=7
    )

    source = open("czjLLM/czjLLM_TextProcessing.py", encoding="utf-8").read()
    assert "project_reduction_transient_cache_policy(ctx, get_param)" in source


def test_cache_key_hashes_prompt_and_uses_allowlisted_model_semantics_only():
    root = _ctx()
    prompt = "PROMPT::SUMMARY::private source text"
    first = semantic_call_cache_key(root, prompt)
    root.model_spec = {
        "model_name": "safe-model",
        "temperature": 0.1,
        "api_key": "secret-b",
        "base_url": "https://private-b",
    }
    same = semantic_call_cache_key(root, prompt)
    assert first == same
    root.model_spec["temperature"] = 0.9
    changed = semantic_call_cache_key(root, prompt)
    assert first != changed
    assert "private source text" not in first
    assert "secret" not in first and "private-" not in first


def test_bounded_lru_retains_no_key_or_payload_in_safe_snapshot():
    cache = RunScopedSemanticCache(ReductionTransientCachePolicy(
        enabled=True,
        max_entries=2,
        max_output_characters=5,
        max_total_output_characters=8,
    ))
    assert cache.put("a" * 64, SemanticCallResult("one", 4, "m"))
    assert cache.put("b" * 64, SemanticCallResult("four", 4, "m"))
    snapshot = cache.safe_snapshot()
    assert snapshot["entries"] == 2 and snapshot["output_characters"] == 7
    assert snapshot["in_flight"] == 0 and snapshot["waiting"] == 0
    assert cache.put("c" * 64, SemanticCallResult("xx", 4, "m"))
    assert cache.get("a" * 64) is None
    hit = cache.get("c" * 64)
    assert hit is not None and hit.output == "xx" and hit.cost_twd == 0
    assert not cache.put("d" * 64, SemanticCallResult("toolong", 4, "m"))
    assert set(cache.safe_snapshot()) == {"entries", "output_characters", "in_flight", "waiting"}


def test_semantic_runtime_cache_hit_skips_second_external_call_and_cost():
    Pipeline.calls.clear()
    root = _ctx()
    runtime = _adapter(root)
    first = runtime.execute(task="SUMMARY", content="items")
    second = runtime.execute(task="SUMMARY", content="items")
    assert len(Pipeline.calls) == 1
    assert first.output == second.output == "answer"
    assert first.cost_twd == 2
    assert second.cost_twd == 0



class BlockingPipeline(Pipeline):
    calls = []
    entered = threading.Event()
    release = threading.Event()

    def proc(self):
        self.entered.set()
        if not self.release.wait(2):
            raise RuntimeError("test release timeout")
        return {"ok": True, "output": "single-flight", "cost": 3}


def test_concurrent_identical_calls_are_coalesced_and_waiters_are_zero_cost():
    BlockingPipeline.calls.clear()
    BlockingPipeline.entered.clear()
    BlockingPipeline.release.clear()
    root = _ctx()
    runtime = _adapter(root, BlockingPipeline)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(runtime.execute, task="SUMMARY", content="same")
        assert BlockingPipeline.entered.wait(1)
        second_future = pool.submit(runtime.execute, task="SUMMARY", content="same")

        cache = ensure_run_scoped_semantic_cache(root)
        assert cache is not None
        deadline = time.monotonic() + 1
        snapshot = cache.safe_snapshot()
        while snapshot["waiting"] < 1 and len(BlockingPipeline.calls) == 1:
            if time.monotonic() >= deadline:
                break
            time.sleep(0.01)
            snapshot = cache.safe_snapshot()

        observed_calls = len(BlockingPipeline.calls)
        observed_waiting = snapshot["waiting"]
        BlockingPipeline.release.set()
        first = first_future.result(timeout=2)
        second = second_future.result(timeout=2)

    assert observed_calls == 1
    assert observed_waiting == 1
    assert len(BlockingPipeline.calls) == 1
    assert first.output == second.output == "single-flight"
    assert first.cost_twd == 3
    assert second.cost_twd == 0


def test_aborted_owner_releases_waiter_for_retry():
    cache = RunScopedSemanticCache(ReductionTransientCachePolicy(enabled=True))
    key = "a" * 64
    cached, owner, flight = cache.reserve(key)
    assert cached is None and owner and flight is not None
    cached, owner, waiter_flight = cache.reserve(key)
    assert cached is None and not owner and waiter_flight is flight
    assert cache.safe_snapshot()["waiting"] == 1

    cache.abort(key, flight)
    assert cache.wait_for_flight(waiter_flight, lambda: None) is None
    cached, retry_owner, retry_flight = cache.reserve(key)
    assert cached is None and retry_owner and retry_flight is not None
    cache.complete(key, retry_flight, SemanticCallResult("retry-ok", 5, "m"))
    hit = cache.get(key)
    assert hit is not None and hit.output == "retry-ok" and hit.cost_twd == 0


def test_cache_is_disabled_by_default_and_semantic_change_misses():
    Pipeline.calls.clear()
    root = _ctx(reduction_transient_cache=ReductionTransientCachePolicy())
    runtime = _adapter(root)
    runtime.execute(task="SUMMARY", content="items")
    runtime.execute(task="SUMMARY", content="items")
    assert len(Pipeline.calls) == 2

    Pipeline.calls.clear()
    root = _ctx()
    runtime = _adapter(root)
    runtime.execute(task="SUMMARY", content="items")
    root.model_spec["temperature"] = 0.8
    runtime.execute(task="SUMMARY", content="items")
    assert len(Pipeline.calls) == 2
