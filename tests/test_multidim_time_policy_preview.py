"""Offline hypothetical comparison; no changes to ES rerun or source data."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from czjLLM.common.multidim_time_policy_preview import (
    summarize_hypothetical_time_rules,
)
from scripts.audit_multidim_event_time import collect, main


def t(value, precision="day"):
    return {"time_raw": None, "time_iso": value, "time_precision": precision}


def record(events, timeline, *, as_text=False):
    payload = [{"Event": events, "Event_Timeline": timeline}]
    return {"_id": "PRIVATE_PK", "_source": {
        "multidim_event_json": json.dumps(payload) if as_text else payload,
        "private_text": "PRIVATE_TEXT",
    }}


def test_hypothetical_comparison_discriminates_unknown_and_date_present():
    docs = [
        record([t("2024-11-11")], []),                     # legacy false fail
        record([t(None, "unknown")], []),                 # no date; source unknown
        record([t(None, "unknown")], [t("2024-11-12")]),  # timeline-only
        record([t("2024-11-13")], [t("2024-11-14")]),    # both dated
        record([t("2024-13-14")], []),                   # invalid
        record([{"time_iso": "2024-11-15"}], [t("2024-11-15")]),
    ]
    report = summarize_hypothetical_time_rules(docs)
    assert report["status"] == "HYPOTHETICAL_NOT_EFFECTIVE_CONFIG"
    assert report["total_documents"] == 6
    counts = report["counts"]
    assert counts["legacy_timeline_min_1_pass"] == 2
    assert counts["legacy_timeline_min_1_fail"] == 2
    assert counts["legacy_time_rule_indeterminate"] == 2
    assert counts["legacy_fail_but_proposed_date_present"] == 1
    assert counts["legacy_fail_but_proposed_time_unknown"] == 1
    assert counts["proposed_date_present"] == 3
    assert counts["proposed_date_unknown_requires_source_review"] == 1
    assert counts["proposed_invalid_or_unverified_requires_review"] == 2
    for forbidden in ("PRIVATE_", "2024-11-11", "private_text", "SECRET"):
        assert forbidden not in json.dumps(report)


def test_preexisting_json_string_and_multiblock_export_are_supported():
    doc = record([t("2024-11-11")], [], as_text=True)
    report = summarize_hypothetical_time_rules([doc])
    assert report["counts"]["legacy_fail_but_proposed_date_present"] == 1
    doc2 = record([t("2024-11-11")], [])
    doc2["_source"]["multidim_event_json"].append({
        "Event": [t(None, "unknown")], "Event_Timeline": [t("2025-11-11")],
    })
    assert summarize_hypothetical_time_rules([doc2])["counts"]["legacy_timeline_min_1_pass"] == 1


def test_bad_structure_not_counted_as_legacy_rule_failure():
    cases = [
        {"_source": {"multidim_event_json": '{"Event":'}},
        {"_source": {"multidim_event_json": []}},
        {"_source": {"multidim_event_json": [{"Event": [], "Event_Timeline": [t("2024-99-99")]}]}},
        [],
        None,
    ]
    report = summarize_hypothetical_time_rules(cases)
    assert report["total_documents"] == 5
    assert report["counts"]["legacy_time_rule_indeterminate"] == 5
    assert report["counts"]["legacy_timeline_min_1_fail"] == 0


def test_local_ndjson_cli_opt_in_redacts_payload_and_does_not_modify_file(tmp_path, capsys):
    path = tmp_path / "PRIVATE_PATH.ndjson"
    lines = [
        record([t("2024-11-11")], []),
        record([t(None, "unknown")], []),
    ]
    path.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    old = path.read_bytes()
    assert main(["--input-ndjson", str(path), "--compare-timeline-min-1"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["counts"]["EVENT_DATE_EMPTY_TIMELINE"] == 1
    assert report["time_rule_comparison"]["counts"]["legacy_fail_but_proposed_date_present"] == 1
    assert "PRIVATE" not in json.dumps(report)
    assert path.read_bytes() == old

    assert main(["--input-ndjson", str(path), "--human", "--compare-timeline-min-1"]) == 0
    output = capsys.readouterr().out
    assert "假設舊規則 Timeline 至少 1 筆日期" in output
    assert "實際有效設定" in output
    assert "PRIVATE" not in output
    assert path.read_bytes() == old

    assert main(["--input-ndjson", str(path)]) == 0
    without_opt_in = json.loads(capsys.readouterr().out)
    assert "time_rule_comparison" not in without_opt_in


def test_invalid_ndjson_still_fails_closed_when_comparison_enabled(tmp_path):
    path = tmp_path / "PRIVATE_DOC.jsonl"
    path.write_bytes(b'{"_source":')
    report = collect(path, compare_timeline_min_1=True)
    assert report["status"] == "UNAVAILABLE"
    assert "time_rule_comparison" not in report
    assert "PRIVATE" not in json.dumps(report)


def test_bounded_document_budget():
    with pytest.raises(ValueError, match="DOCUMENT_LIMIT"):
        summarize_hypothetical_time_rules({} for _ in range(20_001))


def test_standalone_subprocess_utf8_no_pythonpath(tmp_path):
    root = Path(__file__).resolve().parents[1]
    path = tmp_path / "PRIVATE_LOCAL.ndjson"
    path.write_text(json.dumps(record([t("2024-11-11")], [])) + "\n", encoding="utf-8")
    before = path.read_bytes()
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, str(root / "scripts" / "audit_multidim_event_time.py"),
         "--input-ndjson", str(path), "--human", "--compare-timeline-min-1"],
        cwd=tmp_path, env=env, capture_output=True,
        text=True, encoding="utf-8", timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert "假設舊規則 Timeline" in proc.stdout
    assert "PRIVATE" not in proc.stdout
    assert path.read_bytes() == before
