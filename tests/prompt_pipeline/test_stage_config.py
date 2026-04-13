import pytest

from czjLLM.prompt_pipeline.stage_config import normalize_human_stage_spec
from czjLLM.prompt_pipeline.stage_runtime import normalize_stages


def test_normalize_human_stage_spec_supports_defaults_and_alias():
    spec = {
        "defaults": {"input_from": "original", "persist_output": "final"},
        "stages": [
            {"name": "translate", "task": "翻譯"},
            {"name": "summary", "task": "摘要", "from": "previous", "persist": "always"},
        ],
    }
    out = normalize_human_stage_spec(spec)
    assert out[0]["input_from"] == "original"
    assert out[1]["input_from"] == "previous"
    assert out[1]["persist_output"] == "always"

def test_normalize_human_stage_spec_supports_prompt_alias():
    out = normalize_human_stage_spec(
        {"stages": [{"name": "route", "prompt": "請分類", "input_from": "original"}]}
    )
    assert out[0]["name"] == "route"
    assert out[0]["task"] == "請分類"
    assert out[0]["task_key"] == ""


def test_normalize_human_stage_spec_supports_shorthand_dict():
    out = normalize_human_stage_spec({"stages": [{"translate": "翻成中文"}]})
    assert out == [
        {
            "name": "translate",
            "task": "翻成中文",
            "task_key": "",
            "input_from": "original",
            "persist_output": "final",
            "max_attempts": 2,
            "route_by": "",
            "route_map": {},
            "route_value_mode": "task_key",
            "retry_source_on_route_miss": False,
            "debug_print_llm_io": False,
            "debug_print_max_chars": 2000,
        }
    ]


def test_normalize_human_stage_spec_rejects_duplicate_stage_names():
    with pytest.raises(ValueError):
        normalize_human_stage_spec({"stages": [{"name": "s1", "task": "a"}, {"name": "s1", "task": "b"}]})


def test_normalize_human_stage_spec_rejects_invalid_route_value_mode():
    with pytest.raises(ValueError):
        normalize_human_stage_spec({"stages": [{"name": "s1", "task": "a", "route_value_mode": "bad"}]})


def test_stage_runtime_normalize_stages_uses_human_friendly_config():
    stages = normalize_stages(
        {
            "defaults": {"persist_output": "never"},
            "stages": [
                "抽取",
                {"name": "route", "task": "分類", "from": "original"},
            ],
        }
    )
    assert stages[0].persist_output == "never"
    assert stages[1].name == "route"


def test_normalize_human_stage_spec_allows_task_key_without_task():
    out = normalize_human_stage_spec({"stages": [{"name": "分類判定", "task_key": "分類判定"}]})
    assert out[0]["task"] == ""
    assert out[0]["task_key"] == "分類判定"
