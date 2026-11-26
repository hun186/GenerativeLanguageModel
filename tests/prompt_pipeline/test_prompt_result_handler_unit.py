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

def test_unterminated_json_array_is_not_accepted_as_empty_list():
    from czjLLM.prompt_pipeline.result_handler import parse_result

    raw = '[{"text":"unfinished}]\n[{"id":2}]'
    handler = PromptResultHandler(task="to json")
    ok, fixed = handler.validate_json(raw)
    assert (ok, fixed) == (False, "")
    assert parse_result(raw, task="to json") == {"text": raw}


def test_validate_json_ok():
    h = PromptResultHandler(task="")
    ok, fixed = h.validate_json('{"a":1}')
    assert ok and fixed == '{"a":1}'


import json
import pytest

from czjLLM.utilities.json_transport import clean_json_transport


@pytest.mark.parametrize("task", ["to json", "json format Repair"])
def test_json_transport_preserves_literal_payload_markers(task):
    handler = PromptResultHandler(task=task, include_think=False)
    raw = json.dumps({"text": "literal \x60\x60\x60json and \x60\x60\x60; <think>原文</think>"}, ensure_ascii=False)
    assert handler.clean_output(raw) == raw
    assert handler.clean_output(" \n" + raw + "\n") == raw
    fenced = "\x60\x60\x60json\n" + raw + "\n\x60\x60\x60"
    assert handler.clean_output(fenced) == raw
    assert handler.clean_output("<think>model reasoning</think>\n" + fenced) == raw


@pytest.mark.parametrize("raw", [
    "\x60\x60\x60json\n{\"text\":\"unfinished",
    "\x60\x60\x60json\n{\"text\":\"unfinished\"}\n",
    "\x60\x60\x60json\n{\"text\":\"a\"}\n\x60\x60\x60\nextra",
    "<think>reasoning</think>\n{\"text\":\"unfinished",
    "<think>unclosed\n{\"text\":\"a\"}",
    "  {\"text\":\"broken <think>keep me</think> \x60\x60\x60json\",}  ",
])
def test_json_transport_preserves_unproven_output_for_existing_repair(raw):
    assert clean_json_transport(raw) == raw
    assert PromptResultHandler(task="to json").clean_output(raw) == raw


def test_json_transport_keeps_requested_thinking_and_legacy_non_json_behavior():
    raw = '<think>reasoning</think>\n{"x":1}'
    assert clean_json_transport(raw, include_think=True) == raw
    assert clean_json_transport(raw) == '{"x":1}'
    assert clean_json_transport("<think>reasoning</think>\n<EMPTY>") == ""
    assert PromptResultHandler(task="").clean_output("hi<think>secret</think>there") == "hithere"


def test_both_worker_cleanup_paths_use_shared_json_transport():
    from pathlib import Path
    source = Path("czjLLM/prompt_pipeline/pipeline_controller.py").read_text(encoding="utf-8")
    assert source.count("clean_json_transport(retMES, include_think=self.include_think)") == 2
    assert "retMES.replace('\x60\x60\x60json', '').replace('\x60\x60\x60', '')" not in source
