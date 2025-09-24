# tests/prompt_pipeline/test_prompt_pipeline.py
from czjLLM.prompt_pipeline import result_handler

def test_result_handler_parsing_json_string():
    raw_output = '{"answer": "42"}'
    parsed = result_handler.parse_result(raw_output)
    assert parsed["answer"] == "42"

def test_result_handler_parsing_broken_json_repaired():
    raw_output = "```json\n{ \"answer\": 42 }\n```"
    parsed = result_handler.parse_result(raw_output, task="to json")
    assert parsed["answer"] == 42
