from types import SimpleNamespace

import pytest

pytest.importorskip("tqdm")

from czjLLM.prompt_pipeline.pipeline_controller import (  # noqa: E402
    _build_stage_prompt_text, render_stage_task_prompt,
)


def test_public_stage_prompt_renderer_matches_legacy_surface():
    ctx = SimpleNamespace(taskSetting={}, task="ROOT", think_mode=True)
    for task in ("Summarize", {"task": "Summarize"}):
        assert render_stage_task_prompt(task, "content", ctx) == _build_stage_prompt_text(
            task, "content", ctx
        )
