"""One K2 production E2E for bounded nested reduction and shared leaf budget."""

from types import SimpleNamespace

import pytest

from czjLLM.reduction import (
    ExecutableRegistry, ExecutionContext, ExecutionNestingState, PipelineRefExecutable,
    ProductionTaskRuntime, ReductionStage, ReductionStageExecutable,
    StagePipelineExecutable, TokenizerInputPreparer, TokenizerRoundPreparer,
    parse_reduction_config,
)
from czjLLM.reduction.execution_budget import ExecutionBudget


pytestmark = pytest.mark.e2e


def test_bounded_nested_reduction_real_http_shared_budget(fake_openai, tmp_path):
    fake_openai.delay = .04
    budget = ExecutionBudget(2)
    task_pool = {
        "document_summary": {"task": "E2E_SUMMARY", "InputCutLen": 48},
    }
    root = SimpleNamespace(
        task="ROOT", taskSetting=task_pool, model_spec_name="e2e-model",
        model_spec=fake_openai.model_spec, max_tokens=4096, think_mode=True,
        PGMSubDir=str(tmp_path), llm_call_audit_run_id="nested-reduction-e2e",
        llm_call_audit_path=str(tmp_path / "audit.csv"), _execution_budget=budget,
    )
    runtime = ProductionTaskRuntime(root)
    document_pipeline = StagePipelineExecutable([
        {"name": "document_summary", "task": "document_summary", "persist_output": "never"},
    ])
    child_reduction = parse_reduction_config({
        "enabled": True, "profile": "concat_text", "controller": "fixed_rounds",
        "controller_options": {"rounds": 2}, "runtime": {"round_task": "legacy-unused"},
    })
    child = ReductionStage(
        PipelineRefExecutable("document_pipeline"), child_reduction,
        worker_parallelism=2, round_preparer=TokenizerRoundPreparer("document_summary"),
        checkpoint_root=tmp_path / "child-checkpoints",
    )
    registry = ExecutableRegistry({
        "document_pipeline": document_pipeline,
        "document_reduce": ReductionStageExecutable(
            child, TokenizerInputPreparer("document_summary")
        ),
        "document_reduce_alias": PipelineRefExecutable("document_reduce"),
    })
    context = ExecutionContext(
        root, runtime, registry, {}, ExecutionNestingState()
    )
    outer_reduction = parse_reduction_config({
        "enabled": True, "profile": "concat_text", "controller": "single_pass",
    })
    documents = [
        (("ROW_ID=first alpha production document. " * 20) + "ROW_ID=first"),
        (("ROW_ID=second beta production document. " * 20) + "ROW_ID=second"),
    ]
    result = ReductionStage(
        PipelineRefExecutable("document_reduce_alias"), outer_reduction,
        worker_parallelism=2,
    ).execute(documents, context)

    assert result.worker_execution_count == 2
    assert isinstance(result.payload, str) and result.payload.strip()
    assert "first" in result.payload and "second" in result.payload
    assert result.payload.index("first") < result.payload.index("second")
    assert context.nesting == ExecutionNestingState()
    # Multiple initial chunks plus a second child round ran for both documents.
    prompts = "\n".join(str(request["body"]) for request in fake_openai.requests)
    assert prompts.count("ROW_ID=first") > 1 and prompts.count("ROW_ID=second") > 1
    assert len(fake_openai.requests) > 4
    assert not list(tmp_path.glob("**/*stage*manifest*"))
    assert (tmp_path / "audit.csv").exists()
    assert not list(tmp_path.glob("**/*.sqlite"))
    assert not list(tmp_path.glob("**/*.db"))
    assert not list(tmp_path.glob("**/*sql*output*"))
    assert not list(tmp_path.glob("**/*es*output*"))
    snapshot = budget.snapshot()
    assert snapshot.in_use == 0 and snapshot.peak_in_use == 2
    assert snapshot.peak_in_use <= 2
    assert "e2e-dummy-key" not in repr(result.audit)
    assert fake_openai.base_url not in repr(result.audit)
