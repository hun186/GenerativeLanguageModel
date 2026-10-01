"""Offline production-path acceptance for the PR I semantic reducer."""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from czjLLM.reduction import (
    AggregateOutput, CollectionManifest, LogicalWorkUnit, parse_reduction_config,
    reduce_single_pass,
)
from czjLLM.reduction.execution_budget import ExecutionBudget
from czjLLM.reduction.runtime_semantic import SemanticLLMRuntimeAdapter
from czjLLM.sql_mode.collection import SQLiteAggregateSink


pytestmark = pytest.mark.e2e


def test_semantic_composite_real_http_audit_budget_and_idempotent_sink(fake_openai, tmp_path):
    manifest = CollectionManifest("semantic-reports", (
        LogicalWorkUnit("a", {"id": "a", "score": 1}),
        LogicalWorkUnit("a-dup", {"id": "a", "score": 99}),
        LogicalWorkUnit("b", {"id": "b", "score": 5}),
        LogicalWorkUnit("c", {"id": "c", "score": 3}),
    ))
    config = parse_reduction_config({"enabled": True, "profile": "composite", "options": {"steps": [
        {"profile": "dedup", "options": {"key_paths": ["id"]}},
        {"profile": "rank", "options": {"score_path": "score"}},
        {"profile": "top_k", "options": {"k": 2}},
        {"profile": "semantic_llm", "options": {
            "task": "E2E_SEMANTIC_THINK\nE2E_SUMMARY\nBrief the selected items."
        }},
    ]}})
    audit = tmp_path / "llm-audit.csv"
    budget = ExecutionBudget(1)
    ctx = SimpleNamespace(
        task="ROOT", model_spec_name="e2e-model", model_spec=fake_openai.model_spec,
        max_tokens=4096, think_mode=True, PGMSubDir=str(tmp_path),
        llm_call_audit_run_id="semantic-e2e", llm_call_audit_path=str(audit),
        _execution_budget=budget,
    )
    result = reduce_single_pass(
        [unit.payload for unit in manifest.units], config,
        context={"semantic_runtime": SemanticLLMRuntimeAdapter(ctx=ctx)},
    )
    assert result.payload.startswith("SUMMARY::")
    assert "<think>" not in result.payload
    assert "internal reasoning" not in result.payload
    assert len(fake_openai.requests) == 1
    messages = fake_openai.requests[0]["body"]["messages"]
    assert {message.get("role") for message in messages} >= {"system", "user"}
    user_messages = [
        message["content"]
        for message in messages
        if message.get("role") == "user"
    ]
    assert len(user_messages) == 1
    prompt = user_messages[0]
    assert '"id":"b"' in prompt and '"id":"c"' in prompt and '"id":"a"' not in prompt
    assert audit.exists() and "semantic-e2e" in audit.read_text(encoding="utf-8")
    snapshot = budget.snapshot()
    assert snapshot.peak_in_use <= 1 and snapshot.in_use == 0
    assert "e2e-dummy-key" not in repr(result.audit)

    connection = sqlite3.connect(tmp_path / "semantic.sqlite")
    sink = SQLiteAggregateSink(connection); sink.ensure_schema()
    aggregate = AggregateOutput(manifest, "briefing", result.payload)
    sink.upsert(aggregate); sink.upsert(aggregate)
    assert connection.execute("SELECT COUNT(*) FROM collection_aggregates").fetchone() == (1,)
    connection.close()
