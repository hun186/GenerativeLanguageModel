"""Offline characterization of JSON list merging around quoted bracket characters.

Valid JSON must not take the repair path, and quoted text/nested arrays must
survive the legacy combine_json_return compatibility boundary unchanged.
"""
import json

import pytest

from czjLLM.utilities import json_combining


@pytest.mark.parametrize("chunks", [
    [[{"id": 1, "text": "Breaking news ] not an array end"}],
     [{"id": 2, "text": "Policy [ and ] in quotation"}]],
    [[{"id": 1, "quote": 'An escaped " quote followed by ]'}],
     [{"id": 2, "path": r"C:\\docs\\[report]"}]],
    [[{"id": 1, "nested": [[1, 2], [3, [4, 5]]]}],
     [{"id": 2, "nested": ["]", "[", "中文 [ ]"]}]],
], ids=["quoted-brackets", "escaped-quotes-and-backslashes", "nested-arrays"])
def test_valid_json_multi_arrays_preserved_without_repair(monkeypatch, capsys, chunks):
    raw = "\n".join(json.dumps(chunk, ensure_ascii=False) for chunk in chunks)

    def forbid_repair(*_args, **_kwargs):
        pytest.fail("valid quoted-bracket JSON must not invoke repair_json")

    monkeypatch.setattr(json_combining, "repair_json", forbid_repair)
    merged = json.loads(json_combining.robust_merge_json_lists(raw))
    assert merged == [row for chunk in chunks for row in chunk]
    assert capsys.readouterr().out == ""


def test_valid_fenced_json_with_quoted_brackets_no_repair(monkeypatch):
    expected = [{"label": "literal [ ] \\" ] inside text", "events": [1, [2, 3]]}]
    fenced = "```json\n" + json.dumps(expected, ensure_ascii=False) + "\n```"
    monkeypatch.setattr(
        json_combining, "repair_json",
        lambda *_args, **_kwargs: pytest.fail("valid fenced JSON attempted repair"),
    )
    assert json.loads(json_combining.robust_merge_json_lists(fenced)) == expected


def test_legacy_combine_json_return_preserves_quoted_bracket_text_without_repair(
    monkeypatch, capsys,
):
    chunks = [[{"original": "closing ] bracket and opening [", "value": "A"}],
              [{"original": 'escaped " ] still inside', "value": "B"}]]
    raw = "\n".join(json.dumps(chunk, ensure_ascii=False) for chunk in chunks)
    monkeypatch.setattr(
        json_combining, "repair_json",
        lambda *_args, **_kwargs: pytest.fail("valid combined slices attempted repair"),
    )
    combined, error = json_combining.combine_json_return(raw)
    assert error == ""
    assert json.loads(combined) == chunks[0] + chunks[1]
    assert capsys.readouterr().out == ""


def test_existing_repair_fallback_still_handles_malformed_array():
    merged = json.loads(json_combining.robust_merge_json_lists('[{"id": 1,}]'))
    assert merged == [{"id": 1}]
