"""Stored Output Profile audit: synthetic, no live ES, no private document output."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from czjLLM.common.multidim_profile_audit import (
    CATEGORIES, classify_stored_profile, summarize_stored_profiles,
)
from czjLLM.common.multidim_time_audit import classify_stored_document
from scripts.audit_multidim_profile_offline import collect, main


def event(value="2024-07-25", precision="day", event_id="E1"):
    return {
        "event_id": event_id, "time_raw": None,
        "time_iso": value, "time_precision": precision,
    }


def row(events=None, timeline=None):
    return {
        "article_date_iso": None,
        "article_date_precision": "unknown",
        "Event": [event()] if events is None else events,
        "Event_Timeline": [] if timeline is None else timeline,
        "evidence_snippets": [{"event_ids": ["E1"], "text": "SENSITIVE_SYNTHETIC_EVIDENCE"}],
    }


def stored(blocks=None, *, wrapper=True):
    source = {"multidim_event_json": [row()] if blocks is None else blocks}
    return {"_id": "PRIVATE_SOURCE_KEY", "_source": source} if wrapper else source


def test_valid_single_event_date_and_explicit_empty_timeline_not_a_profile_failure():
    doc = stored()
    original = deepcopy(doc)
    assert classify_stored_profile(doc) == "PROFILE_ACCEPTED_EVENT_DATE_EMPTY_TIMELINE"
    assert classify_stored_document(doc) == "EVENT_DATE_EMPTY_TIMELINE"
    assert doc == original


@pytest.mark.parametrize("record,category", [
    (stored([row(timeline=[{
        "event_ids": ["E1"], "time_raw": None,
        "time_iso": "2024-07-26", "time_precision": "day",
    }])]), "PROFILE_ACCEPTED_EVENT_AND_TIMELINE_DATES"),
    (stored([row(events=[event(None, "unknown")], timeline=[{
        "event_ids": ["E1"], "time_raw": None,
        "time_iso": "2024-07-26", "time_precision": "day",
    }])]), "PROFILE_ACCEPTED_TIMELINE_DATE_ONLY"),
    (stored([row(events=[event(None, "unknown")])]),
     "PROFILE_ACCEPTED_DATE_UNKNOWN"),
    (stored([row(events=[event("2024-01-01", "year")])]),
     "PROFILE_ACCEPTED_EVENT_DATE_EMPTY_TIMELINE"),
    (stored([row(events=[event("2024-07-01", "month")])]),
     "PROFILE_ACCEPTED_EVENT_DATE_EMPTY_TIMELINE"),
    (stored([row(events=[event("2024-07-25T12:35:00", "minute")])]),
     "PROFILE_ACCEPTED_EVENT_DATE_EMPTY_TIMELINE"),
    (stored([{**row(events=[]), "evidence_snippets": []}]),
     "PROFILE_ACCEPTED_NO_EVENTS"),
    (stored([]), "OUTPUT_ABSENT"),
    ({"_source": {}}, "OUTPUT_ABSENT"),
    ({"_source": None}, "SOURCE_UNVERIFIED"),
    ({"_source": []}, "SOURCE_UNVERIFIED"),
    ({"multidim_event_json": 3}, "PROFILE_REJECTED"),
])
def test_categories_are_exclusive_and_stable(record, category):
    before = deepcopy(record)
    assert classify_stored_profile(record) == category
    assert record == before


def test_missing_timeline_not_reported_as_explicitly_empty():
    doc = stored(wrapper=False)
    del doc["multidim_event_json"][0]["Event_Timeline"]
    assert classify_stored_profile(doc) == "PROFILE_ACCEPTED_EVENT_DATE_OTHER"


def test_date_check_can_pass_when_linked_evidence_event_id_is_invalid():
    doc = stored()
    doc["_source"]["multidim_event_json"][0]["evidence_snippets"][0]["event_ids"] = ["UNKNOWN_EVENT"]
    # Key finding: time-only checks cannot establish complete linked schema.
    assert classify_stored_document(doc) == "EVENT_DATE_EMPTY_TIMELINE"
    assert classify_stored_profile(doc) == "PROFILE_REJECTED"


@pytest.mark.parametrize("change", [
    lambda r: r["Event"][0].update(time_iso="2024-13-99"),
    lambda r: r["Event"][0].update(time_precision="unknown"),
    lambda r: r["Event"].append(event(event_id="E1")),
    lambda r: r["Event_Timeline"].append({
        "event_ids": ["E9"], "time_raw": None,
        "time_iso": "2024-07-26", "time_precision": "day",
    }),
    lambda r: r["evidence_snippets"][0].pop("event_ids"),
    lambda r: r["evidence_snippets"][0].update(extra_field="PRIVATE_RAW"),
])
def test_existing_profile_rejections_are_aggregated_without_payload(change):
    item = row()
    change(item)
    doc = stored([item])
    original = deepcopy(doc)
    assert classify_stored_profile(doc) == "PROFILE_REJECTED"
    assert doc == original


def test_mixed_blocks_do_not_hide_a_rejected_article():
    valid = row()
    invalid = row(events=[event("2024-13-99")])
    assert classify_stored_profile(stored([valid, invalid])) == "PROFILE_REJECTED"
    assert classify_stored_profile(stored([valid, row(events=[event(None, "unknown")])])) \
        == "PROFILE_ACCEPTED_EVENT_DATE_EMPTY_TIMELINE"


def test_fixed_categories_counts_only_and_no_record_leak():
    docs = [stored(), stored([row(events=[event(None, "unknown")])])]
    counts = summarize_stored_profiles(docs)
    raw = json.dumps(counts)
    assert counts["status"] == "OBSERVED_NOT_PROVEN"
    assert counts["total_documents"] == 2
    assert list(counts["counts"]) == list(CATEGORIES)
    assert sum(counts["counts"].values()) == 2
    assert counts["counts"]["PROFILE_ACCEPTED_EVENT_DATE_EMPTY_TIMELINE"] == 1
    assert counts["counts"]["PROFILE_ACCEPTED_DATE_UNKNOWN"] == 1
    assert counts["actual_rerun_policy"] == "NOT_EVALUATED"
    assert counts["source_date_fidelity"] == "NOT_VERIFIED"
    for private in ("PRIVATE_SOURCE_KEY", "SENSITIVE_SYNTHETIC_EVIDENCE", "2024-07-25"):
        assert private not in raw


def test_empty_and_overbudget_documents_do_not_make_optimistic_report():
    with pytest.raises(ValueError):
        summarize_stored_profiles([])
    with pytest.raises(ValueError):
        summarize_stored_profiles({} for _ in range(20_001))


def test_cli_input_is_unchanged_output_is_redacted(tmp_path, capsys):
    input_file = tmp_path / "PRIVATE_export.jsonl"
    docs = [stored(), stored([row(events=[event(None, "unknown")])])]
    input_file.write_text("".join(json.dumps(d) + "\n" for d in docs), encoding="utf-8")
    original = input_file.read_bytes()
    assert main(["--input-ndjson", str(input_file)]) == 0
    machine = capsys.readouterr().out
    assert json.loads(machine)["total_documents"] == 2
    assert main(["--input-ndjson", str(input_file), "--human"]) == 0
    friendly = capsys.readouterr().out
    assert "Event 有日期、Timeline 明示為空" in friendly
    for private in ("PRIVATE_SOURCE_KEY", "PRIVATE_export", "SENSITIVE_SYNTHETIC_EVIDENCE"):
        assert private not in machine + friendly
    assert input_file.read_bytes() == original


@pytest.mark.parametrize("raw", [
    b"", b"{", b"{}\n{", b"[]\n", b"{\"_source\":{}}",
    b"\n", b"\xff\n",
])
def test_invalid_or_torn_export_returns_no_partial_counts(tmp_path, raw):
    input_file = tmp_path / "source.jsonl"
    input_file.write_bytes(raw)
    result = collect(input_file)
    assert result["status"] == "UNAVAILABLE"
    assert "counts" not in result
    assert result["sink_writeback"] == "NOT_PERFORMED"


def test_reject_input_symlink_without_reading_content(tmp_path):
    real_file = tmp_path / "SENSITIVE_real.jsonl"
    real_file.write_text(json.dumps(stored()) + "\n", encoding="utf-8")
    alias = tmp_path / "alias.jsonl"
    try:
        alias.symlink_to(real_file)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not available")
    assert collect(alias)["status"] == "UNAVAILABLE"


def test_standalone_from_other_working_dir_without_pythonpath(tmp_path):
    path = tmp_path / "source.jsonl"
    path.write_text(json.dumps(stored()) + "\n", encoding="utf-8")
    script = Path(__file__).resolve().parents[2] / "scripts" / "audit_multidim_profile_offline.py"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    completed = subprocess.run(
        [sys.executable, str(script), "--input-ndjson", str(path)],
        cwd=tmp_path, capture_output=True, text=True,
        encoding="utf-8", env=env, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["counts"]["PROFILE_ACCEPTED_EVENT_DATE_EMPTY_TIMELINE"] == 1
    assert not completed.stderr
    assert "PRIVATE_SOURCE_KEY" not in completed.stdout
