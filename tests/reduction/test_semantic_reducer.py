from types import MappingProxyType

import pytest

from czjLLM.reduction import (
    SemanticCallResult, SemanticLLMReducer, SemanticReducerError,
    parse_reduction_config, reduce_single_pass,
)


class Runtime:
    def __init__(self, output="briefing"):
        self.output = output
        self.calls = []

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        return SemanticCallResult(self.output, 1.25, "safe-model")


def test_public_contract_requires_task_and_registry_prototype_fails_closed():
    with pytest.raises(SemanticReducerError):
        SemanticLLMReducer()
    with pytest.raises(SemanticReducerError):
        SemanticLLMReducer("  ")
    reducer = SemanticLLMReducer._registry_prototype()
    with pytest.raises(SemanticReducerError):
        reducer.reduce(["x"], {"semantic_runtime": Runtime()})
    configured = SemanticLLMReducer(" task ")
    assert (configured.profile, configured.contract_version) == ("semantic_llm", "1")
    assert configured.requires_stable_order and not configured.preserves_order


def test_envelope_is_canonical_ordered_and_supports_frozen_values():
    runtime = Runtime()
    frozen = MappingProxyType({"b": (2, 3), "a": 1})
    result = SemanticLLMReducer("TASK").reduce(
        ["plain", {"z": 2, "a": 1}, frozen], {"semantic_runtime": runtime}
    )
    assert runtime.calls == [{"task": "TASK", "content": (
        "--- ITEM 000001 ---\nplain\n--- END ITEM 000001 ---\n\n"
        "--- ITEM 000002 ---\n{\"a\":1,\"z\":2}\n--- END ITEM 000002 ---\n\n"
        "--- ITEM 000003 ---\n{\"a\":1,\"b\":[2,3]}\n--- END ITEM 000003 ---"
    )}]
    assert result.payload == "briefing" and result.changed
    assert result.metrics == {"input_count": 3, "input_character_count": 35,
                              "output_character_count": 8}
    assert set(result.audit) == {"task_sha256", "model_name", "cost_twd"}


def test_failures_are_explicit_and_never_fallback():
    reducer = SemanticLLMReducer("TASK")
    with pytest.raises(SemanticReducerError, match="semantic_runtime"):
        reducer.reduce(["x"])
    with pytest.raises(Exception):
        reducer.reduce([object()], {"semantic_runtime": Runtime()})
    with pytest.raises(SemanticReducerError, match="empty"):
        reducer.reduce(["x"], {"semantic_runtime": Runtime("  ")})

    class Boom:
        def execute(self, **kwargs): raise ValueError("boom")
    with pytest.raises(SemanticReducerError, match="boom"):
        reducer.reduce(["x"], {"semantic_runtime": Boom()})


def test_single_string_changed_is_observational():
    assert not SemanticLLMReducer("TASK").reduce(
        ["same"], {"semantic_runtime": Runtime("same")}
    ).changed


def test_strict_config_alias_schema_and_single_pass_only():
    config = parse_reduction_config({"enabled": True, "profile": "semantic",
                                     "options": {"task": "  preserve me  "}})
    assert config.profile == "semantic_llm" and config.options["task"] == "  preserve me  "
    for options in ({}, {"task": " "}, {"task": 1}, {"task": "x", "api_key": "no"}):
        with pytest.raises(Exception):
            parse_reduction_config({"enabled": True, "profile": "semantic_llm", "options": options})
    with pytest.raises(Exception, match="concat_text only"):
        parse_reduction_config({"enabled": True, "controller": "fixed_rounds",
                                "profile": "semantic_llm", "options": {"task": "x"},
                                "controller_options": {"rounds": 2},
                                "runtime": {"round_task": "r"}})


def test_composite_semantic_final_receives_selected_top_k():
    config = parse_reduction_config({"enabled": True, "profile": "composite", "options": {"steps": [
        {"profile": "dedup", "options": {"key_paths": ["id"]}},
        {"profile": "rank", "options": {"score_path": "score"}},
        {"profile": "top_k", "options": {"k": 2}},
        {"profile": "semantic", "options": {"task": "SUMMARY"}},
    ]}})
    runtime = Runtime()
    items = [{"id": "a", "score": 1}, {"id": "a", "score": 99},
             {"id": "b", "score": 5}, {"id": "c", "score": 3}]
    result = reduce_single_pass(items, config, context={"semantic_runtime": runtime})
    assert result.payload == "briefing"
    assert runtime.calls[0]["content"].count("--- ITEM ") == 2
    assert '"id":"b"' in runtime.calls[0]["content"]
    assert '"id":"c"' in runtime.calls[0]["content"]
    assert '"id":"a"' not in runtime.calls[0]["content"]


@pytest.mark.parametrize("steps", [
    [{"profile": "semantic_llm", "options": {"task": "x"}}, {"profile": "top_k", "options": {"k": 1}}],
    [{"profile": "semantic_llm", "options": {"task": "x"}}, {"profile": "semantic", "options": {"task": "y"}}],
])
def test_invalid_semantic_composites_fail_during_parse(steps):
    with pytest.raises(Exception):
        parse_reduction_config({"enabled": True, "profile": "composite", "options": {"steps": steps}})


def test_semantic_core_has_no_runtime_stack_imports():
    text = open("czjLLM/reduction/reducers/semantic.py", encoding="utf-8").read().lower()
    for forbidden in ("sql_mode", "es_mode", "openai", "promptapipipeline", "callllmapi",
                      "promptgenerator", "tokenizerwrapper", "row merger", "sinks"):
        assert forbidden not in text
