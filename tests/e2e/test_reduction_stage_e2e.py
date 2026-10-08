"""One K1 production E2E across HTTP, stage routing and hierarchical reduction."""

from types import SimpleNamespace

import pytest

from czjLLM.reduction import (
    ExecutableRegistry, ExecutionContext, PipelineRefExecutable, ProductionTaskRuntime,
    QualityAssessment, QualityCheckRejectedError, ReductionStage, StagePipelineExecutable,
    TaskExecutable, TokenizerRoundPreparer, parse_reduction_config,
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


class _MarkerQualityHook:
    contract_version = "e2e-marker-quality-v1"

    def __init__(self, marker):
        self.marker = marker

    def fingerprint_metadata(self, context):
        return {"type": "e2e_marker", "marker": self.marker}

    def evaluate(self, *, payload, context, metrics, provenance):
        present = isinstance(payload, str) and self.marker in payload
        return QualityAssessment(
            accepted=present,
            metrics={
                "required_marker_count": 1,
                "required_marker_present_count": int(present),
                "required_marker_coverage": 1.0 if present else 0.0,
            },
            warnings=() if present else ("required_marker_missing",),
        )


def test_reduction_stage_quality_hook_real_http(fake_openai, tmp_path):
    budget = ExecutionBudget(1)
    root = SimpleNamespace(
        task="ROOT", taskSetting={}, model_spec_name="e2e-model",
        model_spec=fake_openai.model_spec, max_tokens=4096, think_mode=True,
        PGMSubDir=str(tmp_path), llm_call_audit_run_id="reduction-quality-e2e",
        llm_call_audit_path=str(tmp_path / "quality-audit.csv"), _execution_budget=budget,
    )
    context = ExecutionContext(root, ProductionTaskRuntime(root))
    reduction = parse_reduction_config({
        "enabled": True, "profile": "concat_text", "controller": "single_pass",
    })
    with pytest.raises(ValueError, match="exceed 64 entries"):
        QualityAssessment(True, {f"metric_{index}": index for index in range(65)})
    with pytest.raises(ValueError, match="exceed 32 entries"):
        QualityAssessment(True, warnings=tuple(f"warning_{index}" for index in range(33)))

    hook = _MarkerQualityHook("SUMMARY::")
    stage = ReductionStage(TaskExecutable("E2E_SUMMARY"), reduction, quality_hook=hook)
    baseline = ReductionStage(TaskExecutable("E2E_SUMMARY"), reduction)
    assert stage.execution_fingerprint(context) != baseline.execution_fingerprint(context)

    class UnsafeVersionHook(_MarkerQualityHook):
        contract_version = " unsafe version "
    with pytest.raises(ValueError, match="safe identifier"):
        ReductionStage(
            TaskExecutable("E2E_SUMMARY"), reduction,
            quality_hook=UnsafeVersionHook("SUMMARY::"),
        )

    result = stage.execute(["ROW_ID=quality"], context)
    assert result.metrics["quality"] == {
        "required_marker_count": 1,
        "required_marker_present_count": 1,
        "required_marker_coverage": 1.0,
    }
    assert result.audit["quality"] == {
        "accepted": True,
        "contract_version": "e2e-marker-quality-v1",
        "metric_names": (
            "required_marker_count",
            "required_marker_present_count",
            "required_marker_coverage",
        ),
        "warning_count": 0,
    }

    rejected = ReductionStage(
        TaskExecutable("E2E_SUMMARY"), reduction,
        quality_hook=_MarkerQualityHook("NEVER_PRESENT::"),
    )
    with pytest.raises(QualityCheckRejectedError) as caught:
        rejected.execute(["ROW_ID=quality"], context)
    assert caught.value.reason == "quality_check_rejected"
    assert caught.value.assessment.metrics["required_marker_coverage"] == 0.0
    assert "ROW_ID=quality" not in str(caught.value)
    snapshot = budget.snapshot()
    assert snapshot.in_use == 0 and snapshot.peak_in_use == 1
