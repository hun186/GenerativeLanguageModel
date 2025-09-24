# tests/prompt_pipeline/test_prompt_result_handler_unit.py
from czjLLM.prompt_pipeline.result_handler import PromptResultHandler

def test_clean_output_remove_think():
    h = PromptResultHandler(task="", include_think=False)
    raw = "hi<think>secret</think>there"
    assert h.clean_output(raw) == "hithere"

def test_clean_output_strip_json_fence():
    h = PromptResultHandler(task="to json")
    raw = "```json\n{ \"x\": 1 }\n```"
    assert h.clean_output(raw) == '{ "x": 1 }'

def test_validate_json_ok():
    h = PromptResultHandler(task="")
    ok, fixed = h.validate_json('{"a":1}')
    assert ok and fixed == '{"a":1}'
