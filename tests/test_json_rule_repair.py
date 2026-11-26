import json

import pytest

from czjLLM.utilities.json_rule_repair import (
    MAX_CHARS, MAX_EDITS, repair_generic_json, repair_multidim_evidence_quotes,
)


@pytest.mark.parametrize("raw, expected, rules", [
    ('\ufeff{"a":1}', '{"a":1}', ("BOM",)),
    ('\x60\x60\x60json\n{"a":1}\n\x60\x60\x60', '{"a":1}', ("MARKDOWN_FENCE",)),
    ('{"a":["a,]", "x,}"], "b":{"n":2,},}', '{"a":["a,]", "x,}"], "b":{"n":2}}',
     ("TRAILING_COMMA",)),
    ('\ufeff\x60\x60\x60json\n{"a":"x",}\n\x60\x60\x60', '{"a":"x"}',
     ("BOM", "MARKDOWN_FENCE", "TRAILING_COMMA")),
    ('{"quoted":"a\\"b,}",}', '{"quoted":"a\\"b,}"}', ("TRAILING_COMMA",)),
])
def test_generic_exact_edits(raw, expected, rules):
    result = repair_generic_json(raw)
    assert result is not None
    assert result.text == expected and result.rules == rules
    assert json.loads(result.text) == json.loads(expected)
    assert repair_generic_json(result.text) is None
    assert "quoted" not in repr(result)


@pytest.mark.parametrize("raw", [
    '{"a":1}', '{"text":"a"b"}', '{"a":1', '{"a":}',
    '{"a":1,,}', '[,]', '{,}', '{"a":1,"a":2,}',
    '{"a":{"x":1,"x":2},}', '{"a":NaN,}', '{"a":1e999,}',
    '{"text":"line\nbreak",}', '{"text":"bad\\q",}',
    '\x60\x60\x60json\n{}\n\x60\x60\x60\nexplanation', 'prefix {}',
    '\x60\x60\x60json\n"scalar"\n\x60\x60\x60', '\ufeff' + ' ' * MAX_CHARS,
    "[" * 70 + "1," + "]" * 70,
    "[" + ",".join('{"a":1,}' for _ in range(MAX_EDITS + 1)) + "]",
])
def test_generic_declines_unsafe_or_unneeded(raw):
    assert repair_generic_json(raw) is None


def _make_output(text, suffix=''):
    return '[{"evidence_snippets":[{"event_ids":["E2"],"text":' + text + \
        ',"char_start":null,"char_end":null,"confidence":94}],' + \
        '"unrelated":"keep this,}"' + suffix + '}]'


@pytest.mark.parametrize("source", [
    '他见证了中国"蓝盔"部队。',
    '发言人说："我们需要共同努力。"',
    '先有"引语"，再有"另一段"。',
    '"从这里开始"。',
])
def test_profile_exact_source_quote_insertion(source):
    raw = _make_output('"' + source + '"')
    expected = _make_output(json.dumps(source, ensure_ascii=False))
    result = repair_multidim_evidence_quotes(raw, "文章：" + source + "其他段落。")
    assert result is not None
    assert result.text == expected
    assert result.rules == ("SOURCE_EVIDENCE_QUOTE",)
    assert result.edit_count == source.count('"')
    assert json.loads(result.text)[0]["evidence_snippets"][0]["text"] == source
    assert repair_generic_json(raw) is None
    assert repair_multidim_evidence_quotes(result.text, source) is None


def test_profile_preserves_existing_escapes_and_unrelated_tokens():
    source = '路径 C:\\tmp，称"蓝盔"，另有"引语"。'
    token = json.dumps(source, ensure_ascii=False)
    raw = _make_output(token.replace('\\"蓝盔\\"', '"蓝盔"'))
    result = repair_multidim_evidence_quotes(raw, source)
    assert result is not None and result.text == _make_output(token)
    assert result.edit_count == 2


def test_multiple_independent_evidence_items():
    first, second = '他说"甲"。', '他说"乙"。'
    raw = '[{"evidence_snippets":[{"text":"' + first + \
        '"},{"text":"' + second + '"}]}]'
    result = repair_multidim_evidence_quotes(raw, first + "\n" + second)
    assert result is not None and result.edit_count == 4
    assert [x["text"] for x in json.loads(result.text)[0]["evidence_snippets"]] == [first, second]


@pytest.mark.parametrize("raw, source", [
    (_make_output('"他说"甲"。"'), '他说"乙"。'),
    ('[{"text":"他说"甲"。"}]', '他说"甲"。'),
    ('{"evidence_snippets":[{"text":"他说"甲"。"}]}', '他说"甲"。'),
    ('[{"other":{"evidence_snippets":[{"text":"他说"甲"。"}]}}]', '他说"甲"。'),
    (_make_output('"他说"甲"。"')[:-1], '他说"甲"。'),
    (_make_output('"他说"甲"。"', ',"unrelated":0'), '他说"甲"。'),
    (_make_output('"他说"甲"。"', ',"n":NaN'), '他说"甲"。'),
    (_make_output('"他说"甲"。"') + ' trailing', '他说"甲"。'),
    (_make_output('"他说"甲"。"', ',') , '他说"甲"。'),
    (_make_output('"他说"甲"。"'), ' ' * MAX_CHARS + '他说"甲"。'),
    (_make_output('"他说"甲"。"'), ''),
    (_make_output('"他说"甲"。\n"'), '他说"甲"。\n'),
])
def test_profile_refuses_unverified_or_structurally_invalid(raw, source):
    assert repair_multidim_evidence_quotes(raw, source) is None


def test_profile_accepts_one_eligible_boundary_even_with_longer_source():
    raw = _make_output('"a"b"')
    source = 'a"b' + ' ' + 'a"b","char_start":null,"char_end":null,"confidence":94}'
    result = repair_multidim_evidence_quotes(raw, source)
    assert result is not None
    assert result.text == _make_output(json.dumps('a"b'))


def test_profile_refuses_two_source_supported_complete_interpretations():
    raw = '[{"evidence_snippets":[{"text":"a"b","other":"c"}]}]'
    short = 'a"b'
    long = 'a"b","other":"c'
    # Both alternatives parse completely and match the same supplied source.
    short_candidate = '[{"evidence_snippets":[{"text":' + json.dumps(short) + ',"other":"c"}]}]'
    long_candidate = '[{"evidence_snippets":[{"text":' + json.dumps(long) + '}]}]'
    assert json.loads(short_candidate)[0]["evidence_snippets"][0] == {"text": short, "other": "c"}
    assert json.loads(long_candidate)[0]["evidence_snippets"][0] == {"text": long}
    assert repair_multidim_evidence_quotes(raw, short) is not None
    assert repair_multidim_evidence_quotes(raw, long) is None


def test_profile_never_reinterprets_a_legal_string_boundary():
    raw = '[{"evidence_snippets":[{"text":"abc","other": "x" "y"}]}]'
    assert repair_multidim_evidence_quotes(raw, 'abc","other": "x" "y') is None


def test_generic_preserves_fence_inside_payload():
    raw = '\x60\x60\x60json\n{"text":"literal \x60\x60\x60json marker",}\n\x60\x60\x60'
    result = repair_generic_json(raw)
    assert result is not None
    assert result.text == '{"text":"literal \x60\x60\x60json marker"}'


from dataclasses import replace

from czjLLM.utilities.json_rule_policy import (
    JsonRepairPolicy, create_source_span_receipt, parse_json_repair_policy,
    select_rule_candidate, verified_source_span,
)


@pytest.mark.parametrize("spec", [None, {}, {"task": "MultiDim to JSON"}])
def test_rule_policy_default_off(spec):
    assert parse_json_repair_policy(spec) == JsonRepairPolicy()


@pytest.mark.parametrize("value", [None, True, "generic", {"generic": "false"},
                                  {"generic": 1}, {"unknown": True}])
def test_rule_policy_rejects_malformed_flags(value):
    with pytest.raises(ValueError):
        parse_json_repair_policy({"json_rule_repair": value})


def test_explicit_independent_flags():
    assert parse_json_repair_policy({"json_rule_repair": {"generic": True}}) == JsonRepairPolicy(True, False)
    assert parse_json_repair_policy({"json_rule_repair": {"multidim_evidence_quotes": True}}) == JsonRepairPolicy(False, True)


def test_source_receipt_preserves_exact_slice_and_rejects_changed_prompt():
    source = '  他说"甲"。 \n'
    prompt = 'prefix' + source + 'suffix'
    receipt = create_source_span_receipt(prompt, source, 6)
    assert verified_source_span(prompt, receipt) == source
    assert verified_source_span(prompt + "!", receipt) is None
    assert verified_source_span(prompt, replace(receipt, start=7)) is None
    with pytest.raises(ValueError):
        create_source_span_receipt(prompt, source, 0)


def test_generic_gate_requires_opt_in_completed_response_and_contract():
    raw = '{"a":1,}'
    args = dict(policy=JsonRepairPolicy(generic=True), finish_reason="stop",
                validate_candidate=lambda s: json.loads(s) == {"a": 1})
    assert select_rule_candidate(raw, **args).text == '{"a":1}'
    assert select_rule_candidate(raw, **dict(args, policy=JsonRepairPolicy())) is None
    for reason in ("length", "", "content_filter", "tool_calls"):
        assert select_rule_candidate(raw, **dict(args, finish_reason=reason)) is None
    assert select_rule_candidate(raw, **dict(args, validate_candidate=lambda s: False)) is None
    assert select_rule_candidate(raw, **dict(args, validate_candidate=lambda s: 1)) is None

    def unavailable(s):
        raise RuntimeError("contract unavailable")

    assert select_rule_candidate(raw, **dict(args, validate_candidate=unavailable)) is None
    assert raw == '{"a":1,}'


def test_profile_gate_requires_exact_verified_source_not_instruction_text():
    source = '他说"乙"。'
    instruction = 'example: 他说"甲"。'
    prompt = instruction + source
    receipt = create_source_span_receipt(prompt, source, len(instruction))
    args = dict(policy=JsonRepairPolicy(multidim_evidence_quotes=True),
                finish_reason="stop", validate_candidate=lambda s: True,
                dispatched_prompt=prompt, source_receipt=receipt)
    raw = _make_output('"他说"乙"。"')
    result = select_rule_candidate(raw, **args)
    assert result is not None
    assert json.loads(result.text)[0]["evidence_snippets"][0]["text"] == source
    assert select_rule_candidate(_make_output('"他说"甲"。"'), **args) is None
    assert select_rule_candidate(raw, **dict(args, source_receipt=None)) is None
    assert select_rule_candidate(raw, **dict(args, dispatched_prompt=prompt + "!")) is None
    assert select_rule_candidate(raw, **dict(args, policy=JsonRepairPolicy(generic=True))) is None


from czjLLM.utilities.json_rule_policy import (
    receipt_for_trusted_appended_source, rebind_source_span_after_no_think,
)


@pytest.mark.parametrize("task_name", [
    "InfoExtraction-MultiDim-SQLFriendly-to json format",
    "InfoExtraction-MultiDim-Compact-SQLFriendly-to json format",
])
@pytest.mark.parametrize("with_hint", [False, True])
def test_real_multidim_templates_append_exact_original_source(task_name, with_hint, monkeypatch):
    from czjLLM.task_configs import taskSetting_Enrichment as enrichment
    monkeypatch.setattr(enrichment, "USE_MAINFILE_HINT", with_hint)
    source = ' \n☆下列為輸入任務文本：\n他说"甲"。\n '
    prompt = enrichment.taskSetting_Enrichment[task_name]["template"](
        content=source, MainFileName="sample_tika",
    )
    receipt = receipt_for_trusted_appended_source(prompt, source)
    assert verified_source_span(prompt, receipt) == source
    assert receipt.end == len(prompt)
    assert receipt.start == len(prompt) - len(source)
    # The template already contains the marker; the source contains it too.
    # Neither occurrence can move the trusted renderer-supplied boundary.
    assert prompt[:receipt.start].endswith("☆下列為輸入任務文本：\n")
    assert ("主檔名為「sample」" in prompt[:receipt.start]) == with_hint


def test_appended_source_receipt_declines_modified_or_non_appended_input():
    for prompt in ("prefixabc suffix", "prefixABC", "prefixab"):
        with pytest.raises(ValueError):
            receipt_for_trusted_appended_source(prompt, "abc")


@pytest.mark.parametrize("source", ['他说"甲"。', '他说"甲"。 \n'])
def test_dispatch_suffix_binding_preserves_source_or_refuses(source):
    from czjLLM.prompt_pipeline.prompt_generator import finalize_llm_user_content
    prompt = "instruction\n" + source
    receipt = receipt_for_trusted_appended_source(prompt, source)
    unchanged = rebind_source_span_after_no_think(prompt, receipt, prompt)
    assert verified_source_span(prompt, unchanged) == source
    appended = prompt + "\n/no_think"
    rebound = rebind_source_span_after_no_think(prompt, receipt, appended)
    assert verified_source_span(appended, rebound) == source

    # Use the production finalizer, not an approximation of its rstrip().
    finalized = finalize_llm_user_content(prompt, model_name="qwen3")
    rebound = rebind_source_span_after_no_think(prompt, receipt, finalized)
    if source != source.rstrip():
        assert rebound is None
    else:
        assert verified_source_span(finalized, rebound) == source
    assert rebind_source_span_after_no_think(prompt, receipt, prompt + " other") is None
    assert rebind_source_span_after_no_think(prompt + "!", receipt, appended) is None


def test_dispatch_suffix_can_strip_only_whitespace_outside_source():
    source = '他说"甲"。'
    prompt = "prefix" + source + " \n "
    receipt = create_source_span_receipt(prompt, source, 6)
    finalized = prompt.rstrip() + "\n/no_think"
    rebound = rebind_source_span_after_no_think(prompt, receipt, finalized)
    assert verified_source_span(finalized, rebound) == source


from czjLLM.utilities.json_rule_handoff import (
    MAX_HANDOFF_CHARS, bind_dispatched_source_handoff,
    decode_source_handoff, encode_source_handoff,
)


def _source_handoff_fixture():
    source = '原文：他说"甲"。'
    prompt = 'Instruction contains unrelated examples.\n' + source
    receipt = receipt_for_trusted_appended_source(prompt, source)
    generation = "a" * 32
    task = "b" * 64
    wire = encode_source_handoff(prompt, receipt, generation_id=generation, task_sha256=task)
    assert wire is not None
    return source, prompt, receipt, generation, task, wire


def test_source_handoff_round_trip_has_no_raw_content():
    source, prompt, receipt, generation, task, wire = _source_handoff_fixture()
    assert len(wire) <= MAX_HANDOFF_CHARS
    assert source not in wire and "Instruction" not in wire
    assert set(json.loads(wire)) == {
        "version", "generation_id", "task_sha256", "prompt_sha256",
        "source_sha256", "start", "end",
    }
    assert decode_source_handoff(
        wire, prompt, expected_generation_id=generation, expected_task_sha256=task,
    ) == receipt
    dispatched = prompt + "\n/no_think"
    final = bind_dispatched_source_handoff(
        wire, prompt, dispatched,
        expected_generation_id=generation, expected_task_sha256=task,
    )
    assert verified_source_span(dispatched, final) == source


def test_source_handoff_refuses_stale_generation_or_task_even_with_same_prompt():
    source, prompt, receipt, generation, task, wire = _source_handoff_fixture()
    assert decode_source_handoff(
        wire, prompt, expected_generation_id="c" * 32, expected_task_sha256=task,
    ) is None
    assert decode_source_handoff(
        wire, prompt, expected_generation_id=generation, expected_task_sha256="d" * 64,
    ) is None
    assert decode_source_handoff(
        wire, prompt.replace("\n", "\r\n"), expected_generation_id=generation,
        expected_task_sha256=task,
    ) is None
    assert encode_source_handoff(
        prompt + "!", receipt, generation_id=generation, task_sha256=task,
    ) is None
    assert encode_source_handoff(
        prompt, receipt, generation_id="", task_sha256=task,
    ) is None


@pytest.mark.parametrize("key,value", [
    ("version", True), ("version", 2), ("start", True), ("end", 3.5),
    ("start", -1), ("end", MAX_CHARS + 1),
    ("prompt_sha256", "not a digest"), ("source_sha256", "0" * 64),
    ("generation_id", "c" * 32), ("task_sha256", "d" * 64),
    ("generic", True), ("source", "raw text"),
])
def test_source_handoff_refuses_modified_or_unknown_fields(key, value):
    source, prompt, receipt, generation, task, wire = _source_handoff_fixture()
    data = json.loads(wire)
    data[key] = value
    assert decode_source_handoff(
        json.dumps(data), prompt, expected_generation_id=generation, expected_task_sha256=task,
    ) is None


def test_source_handoff_refuses_duplicate_fields_and_unbounded_payloads():
    source, prompt, receipt, generation, task, wire = _source_handoff_fixture()
    for invalid in ("", "{}", "[]", "null", wire[:-1],
                    wire[:-1] + ',"version":1}',
                    wire[:-1] + ',"start":0}',
                    " " * MAX_HANDOFF_CHARS + wire):
        assert decode_source_handoff(
            invalid, prompt, expected_generation_id=generation, expected_task_sha256=task,
        ) is None


def test_source_handoff_declines_unapproved_finalizer_changes():
    source, prompt, receipt, generation, task, wire = _source_handoff_fixture()
    for dispatched in (prompt.replace("甲", "乙"), prompt + " extra", prompt[:-1]):
        assert bind_dispatched_source_handoff(
            wire, prompt, dispatched, expected_generation_id=generation,
            expected_task_sha256=task,
        ) is None
    source = source + " \n"
    prompt = "prefix" + source
    receipt = receipt_for_trusted_appended_source(prompt, source)
    wire = encode_source_handoff(prompt, receipt, generation_id=generation, task_sha256=task)
    assert bind_dispatched_source_handoff(
        wire, prompt, prompt.rstrip() + "\n/no_think",
        expected_generation_id=generation, expected_task_sha256=task,
    ) is None


def _real_rule_worker(monkeypatch, *, policy=None, validator=None):
    from czjLLM.prompt_pipeline import pipeline_controller as pc
    from czjLLM.utilities.json_repair_analysis import validate_repair_detail
    worker = pc.PromptAPIPipeline.__new__(pc.PromptAPIPipeline)
    worker.json_rule_policy = policy
    worker.json_rule_slice_validator = validator
    worker.model_spec = {"model_name": "offline-test"}
    worker.max_tokens = 512
    worker.audit_path = ""
    worker.audit_run_id = ""
    worker.allow_to_retry = True
    calls, events, splits = [], [], []

    def repair(**kwargs):
        calls.append(kwargs["content"])
        return '{"fallback":true}'

    def emit(event, code, outcome, **kwargs):
        detail = kwargs.get("detail")
        if detail is not None:
            assert validate_repair_detail(detail)
        events.append((event, code, outcome, detail))
        return True

    monkeypatch.setattr(pc, "json_format_caller", repair)
    monkeypatch.setattr(pc, "capture_enabled", lambda: False)
    monkeypatch.setattr(pc, "gui_capture_active", lambda: False)
    worker.extract_MainFileName_and_input_text = lambda: ("test", "source", "")
    worker.split_and_generate_new_prompts = lambda **kwargs: splits.append(kwargs)
    worker._emit_json_quality = emit
    return worker, calls, events, splits


def test_worker_rule_success_skips_llm_and_records_method(monkeypatch):
    worker, calls, events, splits = _real_rule_worker(
        monkeypatch, policy=JsonRepairPolicy(generic=True),
        validator=lambda candidate: json.loads(candidate) == {"a": 1},
    )
    raw = '{"a":1,}'
    assert worker.handle_json_output(raw, finish_reason="stop") == ([], '{"a":1}')
    assert not calls and not splits
    assert events[0][:3] == ("slice_json_validation", "JSON_SYNTAX_INVALID", "rejected")
    assert events[1][:3] == ("slice_json_repair", "JSON_REPAIR_SUCCEEDED", "recovered")
    assert events[1][3]["repair_method"] == "RULE_BASED"


@pytest.mark.parametrize("reason,policy,validator", [
    ("stop", None, lambda s: True),
    ("stop", JsonRepairPolicy(), lambda s: True),
    ("stop", JsonRepairPolicy(generic=True), None),
    ("stop", JsonRepairPolicy(generic=True), lambda s: False),
    ("stop", JsonRepairPolicy(generic=True), lambda s: 1),
    ("stop", JsonRepairPolicy(generic=True, multidim_evidence_quotes=True), lambda s: True),
    ("stop", JsonRepairPolicy(multidim_evidence_quotes=True), lambda s: True),
    ("", JsonRepairPolicy(generic=True), lambda s: True),
    ("content_filter", JsonRepairPolicy(generic=True), lambda s: True),
])
def test_worker_rule_refusal_passes_unchanged_raw_to_llm(monkeypatch, reason, policy, validator):
    worker, calls, events, splits = _real_rule_worker(
        monkeypatch, policy=policy, validator=validator,
    )
    raw = ' \n{"a":1,}\n '
    assert worker.handle_json_output(raw, finish_reason=reason) == ([], '{"fallback":true}')
    assert calls == [raw] and not splits
    assert "repair_method" not in events[-1][3]


def test_worker_rule_cannot_override_length_or_valid_json(monkeypatch):
    validator_calls = []
    worker, calls, events, splits = _real_rule_worker(
        monkeypatch, policy=JsonRepairPolicy(generic=True),
        validator=lambda s: validator_calls.append(s) or True,
    )
    valid = '{"a":1}'
    assert worker.handle_json_output(valid, finish_reason="stop") == ([], valid)
    assert worker.handle_json_output('{"a":1,}', finish_reason="length") == ([], "")
    assert not calls and not validator_calls and len(splits) == 1


def test_worker_rule_validator_failure_preserves_llm_fallback(monkeypatch):
    def validator(s):
        raise ValueError("contract failed")
    worker, calls, events, splits = _real_rule_worker(
        monkeypatch, policy=JsonRepairPolicy(generic=True), validator=validator,
    )
    raw = '{"a":1,}'
    assert worker.handle_json_output(raw, finish_reason="stop") == ([], '{"fallback":true}')
    assert calls == [raw] and not splits


def test_rule_method_audit_accepts_only_fixed_enum():
    from czjLLM.utilities.json_repair_analysis import analyze_json_repair, validate_repair_detail
    raw = '{"a":1,}'
    try:
        json.loads(raw)
    except json.JSONDecodeError as exc:
        code, metrics = analyze_json_repair(raw, '{"a":1}', exc)
    detail = dict(metrics, repair_class=code)
    assert validate_repair_detail(detail)
    assert validate_repair_detail(dict(detail, repair_method="RULE_BASED"))
    for invalid in ("raw payload", "LLM", None, True, []):
        assert not validate_repair_detail(dict(detail, repair_method=invalid))


def test_worker_both_paths_forward_finish_reason_for_explicit_rule_policy():
    from pathlib import Path
    source = Path("czjLLM/prompt_pipeline/pipeline_controller.py").read_text(encoding="utf-8")
    assert source.count('if finish_reason == "length" or self._generic_rule_repair_enabled():') == 2
    assert source.count("self.handle_json_output(retMES)") >= 2


@pytest.mark.parametrize("name", [
    "InfoExtraction-MultiDim-SQLFriendly-to json format",
    "InfoExtraction-MultiDim-Compact-SQLFriendly-to json format",
])
@pytest.mark.parametrize("think_mode", [True, False])
@pytest.mark.parametrize("hint", [True, False])
def test_actual_prompt_generator_capture_exact_source(name, think_mode, hint, monkeypatch):
    from types import SimpleNamespace
    from czjLLM.prompt_pipeline.prompt_generator import PromptGenerator
    from czjLLM.task_configs import taskSetting_Enrichment as enrichment

    monkeypatch.setattr(enrichment, "USE_MAINFILE_HINT", hint)
    generator = PromptGenerator(SimpleNamespace(
        task=name, main_file_name="sample_tika", think_mode=think_mode,
        model_spec_name="qwen3.8",
    ))
    source = '原文\n☆下列為輸入任務文本：\n他说"甲"。'
    plain = generator.build(source)
    prompt, receipt = generator.build_with_source_receipt(source)
    assert prompt == plain
    assert receipt is not None
    assert verified_source_span(prompt, receipt) == source
    assert prompt[:receipt.start].endswith("☆下列為輸入任務文本：\n")
    assert prompt.endswith("/no_think") is (not think_mode)


def _untrusted_append_template(content):
    return "☆下列為輸入任務文本：\n" + content


def test_source_capture_refuses_replaced_template_even_if_suffix_matches(monkeypatch):
    from types import SimpleNamespace
    from czjLLM.prompt_pipeline.prompt_generator import PromptGenerator, taskSetting
    name = "InfoExtraction-MultiDim-SQLFriendly-to json format"
    monkeypatch.setitem(taskSetting, name, {"template": _untrusted_append_template})
    generator = PromptGenerator(SimpleNamespace(
        task=name, think_mode=True, model_spec_name="qwen3.8",
    ))
    source = '他说"甲"。'
    prompt, receipt = generator.build_with_source_receipt(source)
    assert prompt == generator.build(source)
    assert receipt is None


def test_source_capture_refuses_raw_task_and_truncated_source_suffix():
    from types import SimpleNamespace
    from czjLLM.prompt_pipeline.prompt_generator import PromptGenerator
    raw_generator = PromptGenerator(SimpleNamespace(
        task="custom prompt", think_mode=True, model_spec_name="qwen3.8",
    ))
    assert raw_generator.build_with_source_receipt("source")[1] is None
    generator = PromptGenerator(SimpleNamespace(
        task="InfoExtraction-MultiDim-SQLFriendly-to json format",
        main_file_name="sample", think_mode=False, model_spec_name="qwen3.8",
    ))
    source = '他说"甲"。 \n'
    prompt, receipt = generator.build_with_source_receipt(source)
    assert prompt == generator.build(source)
    assert prompt.endswith("/no_think")
    assert receipt is None
