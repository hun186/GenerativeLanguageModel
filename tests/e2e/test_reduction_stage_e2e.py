"""One K1 production E2E across HTTP, stage routing and hierarchical reduction."""

from types import SimpleNamespace

import pytest

from czjLLM.reduction import (
    ExecutableRegistry, ExecutionContext, PipelineRefExecutable, ProductionTaskRuntime,
    ReductionStage, StagePipelineExecutable, TokenizerRoundPreparer, parse_reduction_config,
)
from czjLLM.reduction.execution_budget import ExecutionBudget

pytestmark = pytest.mark.e2e


def test_reduction_stage_pipeline_ref_hierarchical_real_http(fake_openai, tmp_path):
    fake_openai.delay = .04
    budget = ExecutionBudget(2)
    root = SimpleNamespace(
        task="ROOT", taskSetting={}, model_spec_name="e2e-model",
        model_spec=fake_openai.model_spec, max_tokens=4096, think_mode=True,
        PGMSubDir=str(tmp_path), llm_call_audit_run_id="reduction-stage-e2e",
        llm_call_audit_path=str(tmp_path / "audit.csv"), _execution_budget=budget,
    )
    pipeline = StagePipelineExecutable([
        {"name": "route", "task": "E2E_ROUTE_FIN", "persist_output": "never"},
        {"name": "summary", "task": "fallback", "input_from": "original",
         "route_by": "route", "route_map": {"FIN": "E2E_SUMMARY"},
         "route_value_mode": "task", "persist_output": "never"},
    ])
    registry = ExecutableRegistry({"summary_pipeline": pipeline})
    reduction = parse_reduction_config({
        "enabled": True, "profile": "concat_text", "controller": "fixed_rounds",
        "controller_options": {"rounds": 2}, "runtime": {"round_task": "legacy-unused"},
    })
    context = ExecutionContext(root, ProductionTaskRuntime(root), registry)
    result = ReductionStage(
        PipelineRefExecutable("summary_pipeline"), reduction, worker_parallelism=2,
        round_preparer=TokenizerRoundPreparer("E2E_ROUND2"),
    ).execute(["ROW_ID=first", "ROW_ID=second"], context)
    assert result.payload.startswith("SUMMARY::") and result.worker_execution_count == 3
    assert result.rounds_completed == 2 and result.stop_reason == "fixed_rounds_complete"
    assert len(registry._entries) == 1 and list(registry._entries) == ["summary_pipeline"]
    assert any("SUMMARY::" in str(request["body"]) for request in fake_openai.requests[4:])
    snapshot = budget.snapshot()
    assert snapshot.in_use == 0 and snapshot.peak_in_use == 2
    assert "e2e-dummy-key" not in repr(result.audit)
    assert not list(tmp_path.glob("**/*stage*manifest*"))
