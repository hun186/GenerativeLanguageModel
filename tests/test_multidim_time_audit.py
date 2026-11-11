"""Pure synthetic and disposable-file proof; no live ES/LLM credentials."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from czjLLM.common.multidim_time_audit import (
    classify_stored_document, summarize_stored_documents,
)
from czjLLM.common.required_output_guard import evaluate_required_output_checks
from scripts.audit_multidim_event_time import collect, main


def event(value, precision="day"):
    return {"time_iso": value, "time_precision": precision, "time_raw": None}


def source(events=None, timeline=None, *, wrapper=True):
    item = {"Event": events if events is not None else [event("2024-07-25")],
            "Event_Timeline": timeline if timeline is not None else []}
    data = {"multidim_event_json": [item]}
    if wrapper:
        return {"_id": "PRIVATE_DOC_ID", "_source": data}
    return data


def test_legacy_timeline_only_rule_would_false_rerun_dated_event():
    doc = source()
    ok, failure = evaluate_required_output_checks(
        doc["_source"], [{
            "full_path": "multidim_event_json.Event_Timeline.time_iso",
            "validator": "date", "format": "iso8601",
            "min_valid_count": 1,
        }]
    )
    assert not ok and failure["found_valid"] == 0
    assert classify_stored_document(doc) == "EVENT_DATE_EMPTY_TIMELINE"
    # No policy change: record only the candidate count.
    summary = summarize_stored_documents([doc])
    assert summary["legacy_timeline_only_false_rerun_candidates"] == 1
    assert summary["actual_rerun_policy"] == "NOT_CHANGED_OR_EVALUATED"


@pytest.mark.parametrize(("record", "status"), [
    (source(timeline=[{**event("2024-07-26"), "event_ids": ["EV_1"]}]),
     "EVENT_AND_TIMELINE_DATES"),
    (source(events=[event(None, "unknown")],
            timeline=[event("2024-07-26")]), "TIMELINE_DATE_ONLY"),
    (source(events=[event(None, "unknown")]), "NO_RELIABLE_DATE"),
    (source(events=[event("2024-13-99")]), "INVALID_TIME_FIELDS"),
    (source(events=[event("2024-07-25", "unknown")]), "INVALID_TIME_FIELDS"),
    (source(events=[event("2024-01-01", "year")]), "EVENT_DATE_EMPTY_TIMELINE"),
    (source(events=[event("2024-07-01", "month")]), "EVENT_DATE_EMPTY_TIMELINE"),
    (source(events=[event("2024-07-25T12:35:00", "minute")]),
     "EVENT_DATE_EMPTY_TIMELINE"),
    ({"multidim_event_json": [{"Event": [event("2024-07-25")]}]},
     "UNVERIFIED_STRUCTURE"),
    ({"multidim_event_json": [{"Event": {}, "Event_Timeline": []}]},
     "UNVERIFIED_STRUCTURE"),
    ({"multidim_event_json": [None]}, "UNVERIFIED_STRUCTURE"),
])
def test_offline_classification_is_conservative(record, status):
    assert classify_stored_document(record) == status


def test_nonempty_timeline_without_time_is_not_called_empty():
    doc = source(timeline=[event(None, "unknown")])
    assert classify_stored_document(doc) == "EVENT_DATE_OTHER_TIMELINE"


def test_multiple_blocks_with_empty_timelines():
    doc = source(wrapper=False)
    doc["multidim_event_json"].append({
        "Event": [event("2025-03-14")], "Event_Timeline": [],
    })
    assert classify_stored_document(doc) == "EVENT_DATE_EMPTY_TIMELINE"


def test_bad_or_stripped_time_fields_never_claim_reliable_date():
    for payload in (
        {"Event": [{"time_iso": "2024-07-25"}], "Event_Timeline": []},
        {"Event": [event(True)], "Event_Timeline": []},
        {"Event": [event(None, "day")], "Event_Timeline": []},
    ):
        record = {"multidim_event_json": [payload]}
        assert classify_stored_document(record) != "EVENT_DATE_EMPTY_TIMELINE"


def test_summary_redacts_all_source_payloads():
    docs = [source(), source(events=[event(None, "unknown")])]
    summary = summarize_stored_documents(docs)
    dump = json.dumps(summary)
    assert "PRIVATE" not in dump
    assert "2024-07-25" not in dump
    assert summary["total_documents"] == 2
    assert summary["counts"]["NO_RELIABLE_DATE"] == 1


def test_private_ndjson_cli_fails_closed_without_mutation(tmp_path, capsys):
    path = tmp_path / "PRIVATE_source.jsonl"
    records = [source(), source(events=[event(None, "unknown")])]
    path.write_text("".join(json.dumps(x) + "\n" for x in records), encoding="utf-8")
    untouched = path.read_bytes()
    assert main(["--input-ndjson", str(path)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["counts"]["EVENT_DATE_EMPTY_TIMELINE"] == 1
    assert path.read_bytes() == untouched
    assert main(["--input-ndjson", str(path), "--human"]) == 0
    chinese = capsys.readouterr().out
    assert "Event 有合規日期、Timeline 為空" in chinese
    assert "PRIVATE" not in chinese
    assert path.read_bytes() == untouched


@pytest.mark.parametrize("raw", [b"{", b"{}", b"{}\n{", b"[]\n", b"\n"])
def test_malformed_or_torn_lines_are_unavailable(tmp_path, raw):
    path = tmp_path / "source.jsonl"
    path.write_bytes(raw)
    result = collect(path)
    # '{}' line is a legitimate structurally-unknown _source.
    expected = "OBSERVED_NOT_PROVEN" if raw == b"{}\n" else "UNAVAILABLE"
    assert result["status"] == expected


def test_oversize_and_symlink_input_rejected(tmp_path):
    path = tmp_path / "source.jsonl"
    path.write_bytes(b"x" * (16 * 1024 * 1024 + 1))
    assert collect(path)["status"] == "UNAVAILABLE"
    private = tmp_path / "PRIVATE_real.jsonl"
    private.write_text(json.dumps(source()) + "\n", encoding="utf-8")
    alias = tmp_path / "alias.jsonl"
    try:
        alias.symlink_to(private)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    assert collect(alias)["status"] == "UNAVAILABLE"


def test_document_budget_fails_closed():
    with pytest.raises(ValueError):
        summarize_stored_documents({} for _ in range(20_001))


def test_standalone_cli_without_pythonpath_or_repo_cwd(tmp_path):
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "audit_multidim_event_time.py"
    path = tmp_path / "PRIVATE_DOC_FILE.jsonl"
    path.write_text(json.dumps(source()) + "\n", encoding="utf-8")
    original = path.read_bytes()
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env["PYTHONIOENCODING"] = "utf-8"
    for args, exit_code, marker in (
        (["--help"], 0, "--input-ndjson"),
        (["--input-ndjson", str(path)], 0, "EVENT_DATE_EMPTY_TIMELINE"),
        (["--input-ndjson", str(path), "--human"], 0, "多維事件時間"),
    ):
        result = subprocess.run(
            [sys.executable, str(script), *args],
            cwd=tmp_path, env=env, capture_output=True,
            text=True, encoding="utf-8", timeout=30,
        )
        assert result.returncode == exit_code, result.stderr
        assert marker in result.stdout, result.stderr
        assert "PRIVATE" not in result.stdout
        assert path.read_bytes() == original
