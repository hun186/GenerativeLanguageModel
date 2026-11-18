"""Synthetic-only unit tests for the six-case operator model A/B metrics CLI."""
import json
from pathlib import Path

from scripts.compare_multidim_news_evidence_ab import (
    FIXTURES, _read_json, compare, main, score_case,
)


def _article(case):
    event_ids = sorted({
        event_id
        for quote in case["expected_quotes"]
        for event_id in quote["event_ids"]
    })
    return [{
        "Event": [{"event_id": eid} for eid in event_ids],
        "evidence_snippets": [
            {"text": q["text"], "event_ids": q["event_ids"]}
            for q in case["expected_quotes"]
        ],
        "Person": [],
        "Involved_Parties": [],
        "Impact": [],
        "Event_Timeline": [],
    }]


def _write_valid_six(directory):
    directory.mkdir()
    for case in json.loads(FIXTURES.read_text(encoding="utf-8")):
        (directory / (case["case_id"] + ".json")).write_text(
            json.dumps(_article(case), ensure_ascii=False), encoding="utf-8",
        )


def test_six_synthetic_outputs_are_measured_not_claimed_real_ab(tmp_path):
    base, candidate = tmp_path / "base", tmp_path / "candidate"
    _write_valid_six(base)
    _write_valid_six(candidate)
    report = compare(base, candidate)
    assert report["case_count"] == report["measured_pairs"] == 6
    assert report["model_settings_equivalence"] == "NOT_VERIFIED"
    assert report["real_model_runs_performed_by_tool"] is False
    assert report["adoption_decision"] == "OPERATOR_REVIEW_REQUIRED"
    for row in report["cases"]:
        assert row["baseline"] == row["candidate"]
        assert row["baseline"]["source_quotes_exact"]
        assert row["baseline"]["event_ids_valid"]
        assert row["baseline"]["event_coverage"]
        assert row["baseline"]["max_280_valid"]
        assert row["baseline"]["expected_quotes_exact"] == row["baseline"]["expected_quotes_total"]


def test_bad_or_missing_model_output_fails_closed_without_raw_text(tmp_path, capsys):
    base, candidate = tmp_path / "base", tmp_path / "candidate"
    _write_valid_six(base)
    _write_valid_six(candidate)
    bad_case = candidate / "news_action_over_date.json"
    bad_case.write_text("RAW_PRIVATE_FRAGMENT:not valid JSON", encoding="utf-8")
    assert main(["--baseline-dir", str(base), "--candidate-dir", str(candidate)]) == 2
    output = capsys.readouterr().out
    assert "RAW_PRIVATE_FRAGMENT" not in output
    result = json.loads(output)
    assert result["measured_pairs"] == 5
    assert next(x for x in result["cases"] if x["case_id"] == "news_action_over_date")[
        "candidate"
    ]["status"] == "MISSING_OR_INVALID_MODEL_JSON"
    bad_case.unlink()
    assert main(["--baseline-dir", str(base), "--candidate-dir", str(candidate)]) == 2
    assert "MISSING_OR_INVALID_MODEL_JSON" in capsys.readouterr().out


def test_source_hallucination_and_dangling_event_ids_are_measured(tmp_path):
    case = json.loads(FIXTURES.read_text(encoding="utf-8"))[0]
    payload = _article(case)
    payload[0]["evidence_snippets"][0]["text"] = "捏造的原文 RAW_NEVER_PRINT"
    payload[0]["evidence_snippets"][0]["event_ids"] = ["E99"]
    scored = score_case(case, payload)
    assert scored["status"] == "MEASURED"
    assert scored["json_valid"] is True
    assert scored["event_ids_valid"] is False
    assert scored["event_coverage"] is False
    assert scored["source_quotes_exact"] is False
    assert scored["expected_quotes_exact"] == 0
    assert "RAW_NEVER_PRINT" not in json.dumps(scored)


def test_news_280_boundary_detects_literal_but_too_long_quote():
    case = next(
        c for c in json.loads(FIXTURES.read_text(encoding="utf-8"))
        if c["case_id"] == "news_280_boundary"
    )
    payload = _article(case)
    payload[0]["evidence_snippets"][0]["text"] = case["source"]
    scored = score_case(case, payload)
    assert scored["source_quotes_exact"] is True
    assert scored["max_280_valid"] is False
    assert scored["expected_quotes_exact"] == 0


def test_malformed_top_level_or_duplicate_key_rejected(tmp_path):
    case = json.loads(FIXTURES.read_text(encoding="utf-8"))[0]
    assert score_case(case, {"Event": []}) == {"status": "INVALID_TOP_LEVEL"}
    file = tmp_path / "dup.json"
    file.write_text('[{"Event":[],"Event":[]} ]', encoding="utf-8")
    import pytest
    with pytest.raises(ValueError, match="duplicate JSON key"):
        _read_json(file)


def test_symlink_result_and_same_directory_fail_closed(tmp_path):
    import pytest
    base, candidate = tmp_path / "base", tmp_path / "candidate"
    _write_valid_six(base)
    _write_valid_six(candidate)
    with pytest.raises(ValueError, match="BASELINE_AND_CANDIDATE_MUST_DIFFER"):
        compare(base, base)
    source = base / "news_action_over_date.json"
    target = candidate / "news_action_over_date.json"
    target.unlink()
    try:
        target.symlink_to(source)
    except (OSError, NotImplementedError):
        pytest.skip("symlink unavailable on this host")
    report = compare(base, candidate)
    assert report["measured_pairs"] == 5
