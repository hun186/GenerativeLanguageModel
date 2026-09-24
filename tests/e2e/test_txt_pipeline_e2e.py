from pathlib import Path

import pytest

from czjLLM.handlers import handle_txt_file
from czjLLM.job_manager.job_config import LLMJobConfig
from czjLLM.prompt_pipeline import pipeline_controller
from czjLLM.prompt_pipeline.dispatch_parallelism import attach_execution_budget


pytestmark = pytest.mark.e2e


def test_txt_handler_creates_todo_dispatches_combines_and_finishes(
    fake_openai, tmp_path, monkeypatch
):
    source_dir = tmp_path / "source"
    backup_dir = tmp_path / "backup"
    prompt_dir = tmp_path / "prompts"
    finished_dir = tmp_path / "finished"
    for directory in (source_dir, backup_dir, prompt_dir, finished_dir):
        directory.mkdir()
    source = source_dir / "document.txt"
    source.write_text("E2E_SUMMARY production TXT", encoding="utf-8")

    ctx = LLMJobConfig()
    ctx.task = "E2E_SUMMARY"
    ctx.model_spec = fake_openai.model_spec
    ctx.model_spec_name = "e2e-model"
    ctx.max_tokens = 64
    ctx.llm_source_dir = str(source_dir)
    ctx.llm_source_backup_dir = str(backup_dir)
    ctx.prompt_dir = str(prompt_dir)
    ctx.temp_txt_finished_dir = str(finished_dir)
    ctx.llm_source_finished_dir = str(finished_dir)
    ctx.PGMSubDir = str(tmp_path)
    ctx.removeFinPromptFile = True
    ctx.mp_for_all_call = True
    ctx.mp_debug = False
    ctx.n_process = 2
    ctx.slice_parallelism = 4
    ctx.debug = False
    ctx.reduction = {"enabled": False, "profile": "concat_text"}
    attach_execution_budget(ctx)

    observed = {}

    def observing_combine(item_path, combine_ctx):
        item_path = Path(item_path)
        observed["todo"] = sorted(
            path.name for path in (item_path / "TODO").glob("*.txt")
        )
        observed["success"] = sorted(
            path.name for path in (item_path / "Success").glob("*.txt")
        )
        return pipeline_controller.combine_api_finished_item(item_path, combine_ctx)

    merge_ops = pipeline_controller.MergeOps(combine=observing_combine)

    def observing_merge(merge_ctx, file_path):
        return pipeline_controller.process_prompt_and_merge(
            merge_ctx, file_path, ops=merge_ops
        )

    monkeypatch.setattr(handle_txt_file, "countdown_pause", lambda _seconds: None)
    monkeypatch.setattr(handle_txt_file, "showTemplate", lambda task=None: None)

    output_name = handle_txt_file.handle_single_input_file(
        str(source),
        ctx=ctx,
        adjust=True,
        pause_seconds=0,
        run_merge=observing_merge,
    )
    output = Path(output_name)
    item = prompt_dir / source.stem
    assert observed["todo"] == []
    assert observed["success"]
    assert output.is_file()
    assert "SUMMARY::" in output.read_text(encoding="utf-8")
    assert not item.exists()
    assert (backup_dir / source.name).is_file()
    assert not source.exists()
    assert ctx._execution_budget.snapshot().in_use == 0
