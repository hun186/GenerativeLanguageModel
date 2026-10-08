import inspect
from types import SimpleNamespace

import pytest

pytest.importorskip("tqdm")

from czjLLM.prompt_pipeline.pipeline_controller import (  # noqa: E402
    _build_stage_prompt_text, process_prompt_and_merge_multistage, render_stage_task_prompt,
)
from czjLLM.prompt_pipeline.prompt_generator import (  # noqa: E402
    finalize_llm_user_content,
    write_prompt_component_metrics,
)
from czjLLM.utilities.llm_call_audit import read_prompt_token_metadata  # noqa: E402


def test_public_stage_prompt_renderer_matches_legacy_surface():
    ctx = SimpleNamespace(taskSetting={}, task="ROOT", think_mode=True)
    for task in ("Summarize", {"task": "Summarize"}):
        assert render_stage_task_prompt(task, "content", ctx) == _build_stage_prompt_text(
            task, "content", ctx
        )



class _FakeTokenizer:
    def count_tokens(self, text):
        return len(str(text).split())


def test_prompt_component_metrics_refresh_replaces_stale_stage_values(tmp_path):
    prompt = tmp_path / "TODO" / "0.txt"
    prompt.parent.mkdir(parents=True)

    write_prompt_component_metrics(
        str(prompt),
        "old task",
        "old template old task",
        tokenizer=_FakeTokenizer(),
        quiet=True,
    )
    first = read_prompt_token_metadata(str(prompt))
    assert first["task_text_tokens"] == 2
    assert first["template_tokens"] == 2

    write_prompt_component_metrics(
        str(prompt),
        "new task text",
        "new stage template new task text",
        tokenizer=_FakeTokenizer(),
        quiet=True,
    )
    refreshed = read_prompt_token_metadata(str(prompt))
    assert refreshed["task_text_tokens"] == 3
    assert refreshed["rendered_prompt_tokens"] == 6
    assert refreshed["template_tokens"] == 3


def test_multistage_prompt_preparation_refreshes_metrics_for_rendered_prompts():
    source = inspect.getsource(process_prompt_and_merge_multistage)
    assert "def _refresh_stage_prompt_metrics" in source
    assert source.count("_refresh_stage_prompt_metrics(") >= 4
    assert "write_prompt_component_metrics(" in source



def test_runtime_qwen_suffix_is_included_in_prompt_component_metrics(tmp_path):
    prompt = tmp_path / "TODO" / "qwen.txt"
    prompt.parent.mkdir(parents=True)

    metadata = write_prompt_component_metrics(
        str(prompt),
        "task text",
        "template task text",
        tokenizer=_FakeTokenizer(),
        model_spec={"model_name": "qwen3.6"},
        quiet=True,
    )

    assert finalize_llm_user_content(
        "template task text",
        model_spec={"model_name": "qwen3.6"},
    ).endswith("/no_think")
    assert metadata["task_text_tokens"] == 2
    assert metadata["rendered_prompt_tokens"] == 4
    assert metadata["template_tokens"] == 2


def test_llm_caller_uses_shared_finalized_user_content_boundary():
    from czjLLM.prompt_pipeline import llm_caller

    source = inspect.getsource(llm_caller.CallLLMAPI)
    assert "finalize_llm_user_content(" in source
    assert "append_no_think_if_applicable(" not in source
