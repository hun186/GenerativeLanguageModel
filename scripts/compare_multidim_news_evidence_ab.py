"""Offline-only metrics for Issue #337's six fixed synthetic model A/B cases.

This reads operator-supplied *raw* model JSON from two local directories.
It never invokes a model, prints article text, writes a report, or authorizes
production adoption. Matching generation settings require external evidence.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "news_evidence_prompt_cases.json"
MAX_RESULT_BYTES = 256 * 1024


def _reject_constant(value):
    raise ValueError("non-standard JSON constant")


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _read_json(path: Path):
    # Do not traverse arbitrary files or output private content on failures.
    if path.is_symlink() or not path.is_file():
        raise ValueError("MISSING_OR_LINKED_RESULT")
    with path.open("rb") as stream:
        raw = stream.read(MAX_RESULT_BYTES + 1)
    if not raw or len(raw) > MAX_RESULT_BYTES:
        raise ValueError("RESULT_SIZE_INVALID")
    return json.loads(
        raw.decode("utf-8"), parse_constant=_reject_constant,
        object_pairs_hook=_unique_pairs,
    )


def score_case(case: dict, payload) -> dict:
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        return {"status": "INVALID_TOP_LEVEL"}
    article = payload[0]
    events = article.get("Event")
    snippets = article.get("evidence_snippets")
    if not isinstance(events, list) or not isinstance(snippets, list) or not snippets:
        return {"status": "INVALID_EVENT_OR_EVIDENCE_ARRAY"}
    if any(not isinstance(e, dict) or not isinstance(e.get("event_id"), str)
           for e in events):
        return {"status": "INVALID_EVENT_ID"}
    ids = [e["event_id"] for e in events]
    if len(set(ids)) != len(ids):
        return {"status": "DUPLICATE_EVENT_ID"}
    if any(not isinstance(x, dict) for x in snippets):
        return {"status": "INVALID_EVIDENCE_ITEM"}
    for field in ("Person", "Involved_Parties", "Impact", "Event_Timeline"):
        entries = article.get(field)
        if not isinstance(entries, list) or any(not isinstance(x, dict) for x in entries):
            return {"status": "INVALID_RELATED_ARRAY"}
    all_related = snippets + sum(
        (article[field] for field in ("Person", "Involved_Parties", "Impact", "Event_Timeline")),
        [],
    )
    links_valid = all(
        isinstance(x.get("event_ids"), list)
        and len(x["event_ids"]) == len(set(map(str, x["event_ids"])))
        and all(isinstance(i, str) and i in ids for i in x["event_ids"])
        for x in all_related
    )
    quote_values = [x.get("text") for x in snippets]
    quote_types_valid = all(isinstance(x, str) and bool(x) for x in quote_values)
    literal_quotes = quote_types_valid and all(x in case["source"] for x in quote_values)
    length_valid = (
        case["mode"] != "general_news" or
        (quote_types_valid and all(len(x) <= 280 for x in quote_values))
    )
    expected = [x["text"] for x in case["expected_quotes"]]
    coverage = sum(1 for x in expected if x in quote_values)
    event_covered = links_valid and all(
        any(eid in x["event_ids"] for x in snippets) for eid in ids
    )
    return {
        "status": "MEASURED",
        "json_valid": True,
        "event_count": len(events),
        "evidence_count": len(snippets),
        "event_ids_valid": links_valid,
        "event_coverage": event_covered,
        "source_quotes_exact": literal_quotes,
        "max_280_valid": length_valid,
        "expected_quotes_exact": coverage,
        "expected_quotes_total": len(expected),
        "first_evidence_is_expected": bool(quote_values and quote_values[0] in expected),
        "timeline_count": len(article["Event_Timeline"]),
    }


def _measure_file(case: dict, directory: Path) -> dict:
    try:
        payload = _read_json(directory / (case["case_id"] + ".json"))
    except (ValueError, UnicodeError, OSError, json.JSONDecodeError):
        return {"status": "MISSING_OR_INVALID_MODEL_JSON"}
    return score_case(case, payload)


def compare(baseline: Path, candidate: Path) -> dict:
    cases = json.loads(FIXTURES.read_text(encoding="utf-8"))
    if len(cases) != 6 or len({c["case_id"] for c in cases}) != 6:
        raise ValueError("FIXTURE_SET_INVALID")
    if baseline.resolve() == candidate.resolve():
        raise ValueError("BASELINE_AND_CANDIDATE_MUST_DIFFER")
    rows = [
        {
            "case_id": case["case_id"],
            "baseline": _measure_file(case, baseline),
            "candidate": _measure_file(case, candidate),
        }
        for case in cases
    ]
    measured_pairs = sum(
        row["baseline"]["status"] == row["candidate"]["status"] == "MEASURED"
        for row in rows
    )
    return {
        "scope": "synthetic_fixed_six_offline_model_output_metrics",
        "model_settings_equivalence": "NOT_VERIFIED",
        "real_model_runs_performed_by_tool": False,
        "case_count": len(rows),
        "measured_pairs": measured_pairs,
        "adoption_decision": "OPERATOR_REVIEW_REQUIRED",
        "cases": rows,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = compare(args.baseline_dir, args.candidate_dir)
    except (OSError, ValueError):
        print('{"status":"OFFLINE_AB_INPUT_INVALID"}')
        return 2
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result["measured_pairs"] == 6 else 2


if __name__ == "__main__":
    raise SystemExit(main())
