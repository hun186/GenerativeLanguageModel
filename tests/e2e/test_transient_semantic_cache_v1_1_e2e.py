from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import threading
import time
from types import SimpleNamespace

import pytest

from czjLLM.reduction.runtime_semantic import SemanticLLMRuntimeAdapter, SemanticRuntimeError
from czjLLM.reduction.transient_cache import (
    ReductionTransientCachePolicy,
    ensure_run_scoped_semantic_cache,
)


pytestmark = pytest.mark.e2e


class Tokenizer:
    def __init__(self, **_kwargs):
        pass

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
        self.model_spec = dict(kwargs["model_spec"])
        self.calls.append(kwargs)

    def proc(self):
        return {"ok": True, "output": "briefing", "cost": 1.5}


class BlockingPipeline(Pipeline):
    calls = []
    entered = threading.Event()
    release = threading.Event()

    def proc(self):
        self.entered.set()
        if not self.release.wait(2):
            raise RuntimeError("single-flight E2E release timeout")
        return {"ok": True, "output": "coalesced", "cost": 2.5}


class FailOncePipeline(Pipeline):
    calls = []
    entered = threading.Event()
    release_failure = threading.Event()
    attempt_lock = threading.Lock()
    attempts = 0

    def proc(self):
        with self.attempt_lock:
            type(self).attempts += 1
            attempt = type(self).attempts
        if attempt == 1:
            self.entered.set()
            if not self.release_failure.wait(2):
                raise RuntimeError("failure-retry E2E release timeout")
            raise RuntimeError("planned owner failure")
        return {"ok": True, "output": "retried", "cost": 3.5}


@contextmanager
def lease(*_args):
    yield 1


def _root(*, temperature=0.1):
    return SimpleNamespace(
        task="ROOT",
        taskSetting={"ROOT": {"task": "root"}},
        model_spec_name="safe-profile",
        max_tokens=100,
        model_spec={
            "model_name": "safe-model",
            "temperature": temperature,
            "api_key": "not-part-of-cache-identity",
            "base_url": "https://not-part-of-cache-identity",
        },
        think_mode=False,
        PGMSubDir=".",
        llm_call_audit_run_id="",
        llm_call_audit_path="",
        reduction_transient_cache=ReductionTransientCachePolicy(
            enabled=True, max_entries=4, max_output_characters=100,
            max_total_output_characters=400,
        ),
    )


def _runtime(root, pipeline_factory=Pipeline):
    return SemanticLLMRuntimeAdapter(
        ctx=root,
        tokenizer_factory=Tokenizer,
        prompt_generator_factory=Generator,
        pipeline_factory=pipeline_factory,
        lease_factory=lease,
    )


def test_run_scoped_semantic_cache_skips_duplicate_external_call_without_becoming_authority():
    Pipeline.calls.clear()
    root = _root()
    runtime = _runtime(root)

    first = runtime.execute(task="SUMMARY", content="same items")
    second = runtime.execute(task="SUMMARY", content="same items")

    assert len(Pipeline.calls) == 1
    assert first.output == second.output == "briefing"
    assert first.cost_twd == 1.5
    assert second.cost_twd == 0.0

    # A semantic model-setting change must miss the run-local memo.
    root.model_spec["temperature"] = 0.9
    third = runtime.execute(task="SUMMARY", content="same items")
    assert len(Pipeline.calls) == 2
    assert third.cost_twd == 1.5

    # A fresh root run has no reusable entry even when semantics match.
    fresh_runtime = _runtime(_root(temperature=0.9))
    fresh_runtime.execute(task="SUMMARY", content="same items")
    assert len(Pipeline.calls) == 3

    # Concurrent identical misses use one external call. The second caller
    # waits cooperatively for the owner's successful result.
    BlockingPipeline.calls.clear()
    BlockingPipeline.entered.clear()
    BlockingPipeline.release.clear()
    concurrent_root = _root()
    concurrent_runtime = _runtime(concurrent_root, BlockingPipeline)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(
            concurrent_runtime.execute, task="SUMMARY", content="parallel same"
        )
        assert BlockingPipeline.entered.wait(1)
        second_future = pool.submit(
            concurrent_runtime.execute, task="SUMMARY", content="parallel same"
        )

        cache = ensure_run_scoped_semantic_cache(concurrent_root)
        assert cache is not None
        deadline = time.monotonic() + 1
        snapshot = cache.safe_snapshot()
        while snapshot["waiting"] < 1 and len(BlockingPipeline.calls) == 1:
            if time.monotonic() >= deadline:
                break
            time.sleep(0.01)
            snapshot = cache.safe_snapshot()

        calls_before_release = len(BlockingPipeline.calls)
        waiters_before_release = snapshot["waiting"]
        BlockingPipeline.release.set()
        owner_result = first_future.result(timeout=2)
        waiter_result = second_future.result(timeout=2)

    assert calls_before_release == 1
    assert waiters_before_release == 1
    assert len(BlockingPipeline.calls) == 1
    assert owner_result.output == waiter_result.output == "coalesced"
    assert owner_result.cost_twd == 2.5
    assert waiter_result.cost_twd == 0.0


def test_run_scoped_semantic_cache_releases_waiter_to_retry_after_owner_failure():
    FailOncePipeline.calls.clear()
    FailOncePipeline.entered.clear()
    FailOncePipeline.release_failure.clear()
    FailOncePipeline.attempts = 0
    root = _root()
    runtime = _runtime(root, FailOncePipeline)

    with ThreadPoolExecutor(max_workers=2) as pool:
        owner_future = pool.submit(runtime.execute, task="SUMMARY", content="retry same")
        assert FailOncePipeline.entered.wait(1)
        waiter_future = pool.submit(runtime.execute, task="SUMMARY", content="retry same")

        cache = ensure_run_scoped_semantic_cache(root)
        assert cache is not None
        deadline = time.monotonic() + 1
        snapshot = cache.safe_snapshot()
        while snapshot["waiting"] < 1 and len(FailOncePipeline.calls) == 1:
            if time.monotonic() >= deadline:
                break
            time.sleep(0.01)
            snapshot = cache.safe_snapshot()

        calls_before_failure = len(FailOncePipeline.calls)
        waiters_before_failure = snapshot["waiting"]
        FailOncePipeline.release_failure.set()

        with pytest.raises(SemanticRuntimeError, match="planned owner failure"):
            owner_future.result(timeout=2)
        retried = waiter_future.result(timeout=2)

    assert calls_before_failure == 1
    assert waiters_before_failure == 1
    assert len(FailOncePipeline.calls) == 2
    assert retried.output == "retried"
    assert retried.cost_twd == 3.5
