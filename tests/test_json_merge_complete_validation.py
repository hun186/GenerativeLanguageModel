"""Pure offline tests of opt-in complete-result JSON validation.

The legacy batch combiner remains tolerant by default. Standalone result
validation must never mistake skipped/unknown segments for complete success.
"""
import json

import pytest

from czjLLM.prompt_pipeline.result_handler import PromptResultHandler, parse_result
from czjLLM.utilities import json_combining


def test_nonempty_nonjson_cannot_be_a_successful_empty_array():
    original = "no JSON array was returned"
    assert json.loads(json_combining.robust_merge_json_lists(original)) == []
    with pytest.raises(ValueError, match="JSON_ARRAY_SEGMENT_MISSING"):
        json_combining.robust_merge_json_lists(original, require_complete=True)
    ok, fixed = PromptResultHandler(task="to json").validate_json(original)
    assert (ok, fixed) == (False, "")
    assert parse_result(original, task="to json") == {"text": original}


def test_partial_invalid_array_is_not_silently_accepted_as_complete(
    monkeypatch, capsys,
):
    marker = "PRIVATE_ROW_CONTENT_NEVER_PRINT"
    first = json.dumps([{"id": 1}], ensure_ascii=False)
    malformed = '[{"text":"' + marker + '","score": }]'
    original = first + "\n" + malformed

    def fail_repair(_raw, **_kwargs):
        raise ValueError("PRIVATE_REPAIR_EXCEPTION_NEVER_PRINT")

    monkeypatch.setattr(json_combining, "repair_json", fail_repair)
    assert json.loads(json_combining.robust_merge_json_lists(original)) == [
        {"id": 1},
    ]  # The pre-existing batch combiner retains its tolerant default.

    with pytest.raises(ValueError, match="JSON_ARRAY_SEGMENT_SKIPPED"):
        json_combining.robust_merge_json_lists(
            original, require_complete=True,
        )
    with pytest.raises(ValueError, match="JSON_ARRAY_SEGMENT_SKIPPED"):
        json_combining.combine_json_return(
            original, require_complete=True,
        )

    handler = PromptResultHandler(task="to json")
    assert handler.validate_json(original) == (False, "")
    assert parse_result(original, task="to json") == {"text": original}
    output = capsys.readouterr().out
    assert marker not in output
    assert "PRIVATE_REPAIR_EXCEPTION_NEVER_PRINT" not in output


def test_repaired_nonarray_shape_is_not_accepted(monkeypatch):
    malformed = '[{"id": }]'
    monkeypatch.setattr(
        json_combining, "repair_json", lambda _raw: '{"replacement": true}',
    )
    assert json.loads(json_combining.robust_merge_json_lists(malformed)) == []
    with pytest.raises(ValueError, match="JSON_ARRAY_SEGMENT_SKIPPED"):
        json_combining.robust_merge_json_lists(
            malformed, require_complete=True,
        )
    assert PromptResultHandler(task="to json").validate_json(malformed) == (
        False, "",
    )


def test_successful_local_repair_and_empty_array_are_still_accepted(monkeypatch):
    malformed = '[{"id": 1,}]'
    expected = [{"id": 1}]
    monkeypatch.setattr(
        json_combining, "repair_json", lambda _raw: json.dumps(expected),
    )
    assert json.loads(json_combining.robust_merge_json_lists(
        malformed, require_complete=True,
    )) == expected
    result, failure = json_combining.combine_json_return(
        malformed, require_complete=True,
    )
    assert failure == ""
    assert json.loads(result) == expected

    handler = PromptResultHandler(task="to json")
    assert handler.validate_json("[]") == (True, "[]")
    assert parse_result("[]", task="to json") == []
    assert handler.validate_json('{"ok": true}') == (True, '{"ok": true}')


def test_valid_multiple_arrays_are_complete_without_repair(monkeypatch):
    first = [{"id": 1, "note": "quoted ] bracket"}]
    second = [{"id": 2, "nested": [1, [2, 3]]}]
    original = "\n".join(json.dumps(x) for x in (first, second))

    def repair_must_not_run(_raw, **_kwargs):
        pytest.fail("Valid arrays should not be repaired")

    monkeypatch.setattr(json_combining, "repair_json", repair_must_not_run)
    result = json.loads(json_combining.robust_merge_json_lists(
        original, require_complete=True,
    ))
    assert result == first + second
    assert json.loads(json_combining.combine_json_return(
        original, require_complete=True,
    )[0]) == first + second
    assert parse_result(original, task="to json") == first + second


def test_existing_incomplete_array_exception_remains_distinct():
    original = '[{"text":"unterminated}]\n[{"id": 2}]'
    with pytest.raises(ValueError, match="JSON_ARRAY_SEGMENT_INCOMPLETE"):
        json_combining.robust_merge_json_lists(
            original, require_complete=True,
        )
    assert PromptResultHandler(task="to json").validate_json(original) == (
        False, "",
    )
