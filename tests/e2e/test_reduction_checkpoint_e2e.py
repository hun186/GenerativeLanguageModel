from pathlib import Path
from types import SimpleNamespace

import pytest

from czjLLM.prompt_pipeline.dispatch_parallelism import attach_execution_budget
from czjLLM.utilities.combine_utils import combine_api_finished_item


pytestmark = pytest.mark.e2e


def _context(tmp_path, fake_openai, round_task="E2E_ROUND2", capacity=2):
    ctx = SimpleNamespace(
        task="initial-map",
        taskSetting={},
        prompt_dir=str(tmp_path / "Prompt"),
        temp_txt_finished_dir=str(tmp_path / "Finished"),
        llm_source_finished_dir=str(tmp_path / "Finished"),
        llm_source_dir=str(tmp_path / "Source"),
        PGMSubDir=str(tmp_path),
        model_spec=fake_openai.model_spec,
        model_spec_name="e2e-model",
        max_tokens=64,
        think_mode=True,
        removeFinPromptFile=True,
        mp_for_all_call=True,
        mp_debug=False,
        n_process=2,
        slice_parallelism=4,
        execution_budget_capacity=capacity,
        merge_slices=False,
        debug=False,
        llm_call_audit_run_id="",
        llm_call_audit_path="",
        reduction={
            "enabled": True,
            "profile": "concat_text",
            "controller": "fixed_rounds",
            "controller_options": {"rounds": 2},
            "runtime": {"round_task": round_task},
        },
    )
    Path(ctx.prompt_dir).mkdir(exist_ok=True)
    Path(ctx.temp_txt_finished_dir).mkdir(exist_ok=True)
    attach_execution_budget(ctx)
    return ctx


def test_d2_local_http_terminal_checkpoint_resume_and_identity(fake_openai, tmp_path):
    item = tmp_path / "Prompt" / "hierarchical"
    success = item / "Success"
    success.mkdir(parents=True)
    (success / "0000.txt").write_text("initial-a", encoding="utf-8")
    (success / "0001.txt").write_text("initial-b", encoding="utf-8")

    first_ctx = _context(tmp_path, fake_openai)
    first_path = Path(combine_api_finished_item(str(item), first_ctx))
    first_payload = first_path.read_text(encoding="utf-8")
    first_count = len(fake_openai.requests)
    assert first_count > 0
    assert first_payload.startswith("REDUCED::")
    assert (item / ".reduction" / "runtime" / "round-0002").is_dir()
    run_dirs = set((item / ".reduction" / "checkpoints").iterdir())
    assert run_dirs

    resumed_path = Path(combine_api_finished_item(str(item), first_ctx))
    assert resumed_path.read_text(encoding="utf-8") == first_payload
    assert len(fake_openai.requests) - first_count == 0

    changed_ctx = _context(tmp_path, fake_openai, round_task="E2E_ROUND2_CHANGED")
    combine_api_finished_item(str(item), changed_ctx)
    assert len(fake_openai.requests) > first_count
    changed_run_dirs = set((item / ".reduction" / "checkpoints").iterdir())
    assert changed_run_dirs > run_dirs

    before_capacity_only = len(fake_openai.requests)
    capacity_ctx = _context(
        tmp_path, fake_openai, round_task="E2E_ROUND2_CHANGED", capacity=8
    )
    combine_api_finished_item(str(item), capacity_ctx)
    assert len(fake_openai.requests) == before_capacity_only
    assert capacity_ctx._execution_budget.snapshot().in_use == 0
