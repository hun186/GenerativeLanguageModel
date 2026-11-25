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
