"""Offline Evidence reference coverage counts; not source-fidelity validation."""
from copy import deepcopy
import json

from czjLLM.common.multidim_index_sample_audit import summarize_structured_sample


def _block(events=None, evidence=None):
    if events is None:
        events = [{"event_id": "SENSITIVE_ID", "time_iso": "2024-01-01",
                   "time_raw": None, "time_precision": "day"}]
    return {
        "article_date_iso": None, "article_date_precision": "unknown",
        "Event": events, "Event_Timeline": [],
        "evidence_snippets": [] if evidence is None else evidence,
    }


def _doc(marker, blocks):
    return {"_index": "news_test", "_id": marker,
            "_source": {"multidim_event_json": blocks}}


def _report(*docs):
    return summarize_structured_sample(100, 10, list(docs))


def test_all_blank_evidence_is_not_automatically_a_bad_or_rerunnable_document():
    d = _doc("SECRET_A", [_block()])
    report = _report(d)
    assert report["evidence_reference_counts"]["EVENTS_WITHOUT_EVIDENCE"] == 1
    assert report["profile_counts"]["PROFILE_ACCEPTED_EVENT_DATE_EMPTY_TIMELINE"] == 1
    assert report["effective_runtime_rerun"] == "NOT_EVALUATED"
    assert report["source_date_fidelity"] == "NOT_VERIFIED"
    assert report["profile_accepted_event_ids_observed"] == 1
    assert report["event_ids_with_nonempty_text_references"] == 0


def test_true_no_event_document_with_empty_evidence_is_valid():
    d = _doc("SECRET_B", [_block(events=[])])
    report = _report(d)
    assert report["evidence_reference_counts"]["NO_EVENTS_NO_EVIDENCE"] == 1
    assert report["profile_counts"]["PROFILE_ACCEPTED_NO_EVENTS"] == 1
    assert report["profile_accepted_event_ids_observed"] == 0


def test_linked_evidence_is_not_evidence_source_fidelity():
    d = _doc("SECRET_C", [_block(evidence=[
        {"event_ids": ["SENSITIVE_ID"], "text": "private reference text"}])])
    before = deepcopy(d)
    report = _report(d)
    assert report["evidence_reference_counts"]["EVENTS_ALL_REFERENCED"] == 1
    assert report["evidence_reference_scope"] == "BLOCK_LOCAL_IDS_ONLY_NOT_SOURCE_VERIFIED"
    assert report["event_ids_with_nonempty_text_references"] == 1
    assert d == before
    raw = json.dumps(report)
    for private in ("SECRET_C", "SENSITIVE_ID", "private reference text"):
        assert private not in raw


def test_partial_reference_coverage_counts_distinct_event_ids_once():
    b = _block(events=[
        {"event_id": "E1", "time_iso": None, "time_raw": None, "time_precision": "unknown"},
        {"event_id": "E2", "time_iso": None, "time_raw": None, "time_precision": "unknown"},
    ], evidence=[
        {"event_ids": ["E1"], "text": "first"},
        {"event_ids": ["E1"], "text": "duplicate linked snippet"},
    ])
    report = _report(_doc("private", [b]))
    assert report["evidence_reference_counts"]["EVENTS_PARTIALLY_REFERENCED"] == 1
    assert report["profile_accepted_event_ids_observed"] == 2
    assert report["event_ids_with_nonempty_text_references"] == 1


def test_matching_id_in_a_different_block_never_counts_as_a_link():
    b1 = _block(events=[
        {"event_id": "E1", "time_iso": None, "time_raw": None,
         "time_precision": "unknown"},
    ], evidence=[])
    b2 = _block(events=[], evidence=[{
        "event_ids": [], "text": "SENSITIVE_ORPHAN"
    }])
    report = _report(_doc("private-cross-block", [b1, b2]))
    assert report["evidence_reference_counts"]["EVENTS_WITH_ROWS_NO_ATTRIBUTABLE_TEXT"] == 1
    assert report["event_ids_with_nonempty_text_references"] == 0
    assert report["effective_runtime_rerun"] == "NOT_EVALUATED"


def test_empty_evidence_text_does_not_imply_attributable_evidence():
    d = _doc("private-no-text", [_block(evidence=[
        {"event_ids": ["SENSITIVE_ID"], "text": ""}])])
    report = _report(d)
    assert report["evidence_reference_counts"]["EVENTS_WITH_ROWS_NO_ATTRIBUTABLE_TEXT"] == 1


def test_unverified_profile_never_inflates_evidence_coverage():
    d = _doc("private-bad", [{"Event": []}])
    report = _report(d)
    assert report["evidence_reference_counts"]["PROFILE_UNVERIFIED"] == 1
    assert report["profile_accepted_event_ids_observed"] == 0
