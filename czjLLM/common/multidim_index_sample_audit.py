"""Offline, aggregate-only interpretation of an ES structured-output sample.

Only anonymous counters are returned; ES _source, document identifiers, raw
news, Event IDs and query results never leave the local operator process.
This estimates neither full-index rerun candidates nor source-fidelity.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from czjLLM.common.multidim_profile_audit import (
    CATEGORIES as PROFILE_CODES, classify_stored_profile,
)
from czjLLM.common.multidim_time_audit import (
    CODES as TIME_CODES, classify_stored_document,
)
from czjLLM.common.required_output_guard import evaluate_required_output_checks
from czjLLM.es_mode.output_profiles.multidim_event import normalize_multidim_event_payload

EVIDENCE_COVERAGE_CODES = (
    "PROFILE_UNVERIFIED",
    "NO_EVENTS_NO_EVIDENCE",
    "NO_EVENTS_WITH_EVIDENCE_ROWS",
    "EVENTS_WITHOUT_EVIDENCE",
    "EVENTS_WITH_ROWS_NO_ATTRIBUTABLE_TEXT",
    "EVENTS_PARTIALLY_REFERENCED",
    "EVENTS_ALL_REFERENCED",
)


def _evidence_coverage(source: dict, profile_code: str) -> tuple[str, int, int]:
    """Count event IDs linked to text in their OWN article block only.

    This does not verify paragraph/source attribution, quote fidelity,
    relevance, date linkage or suitability as a SRAF citation.
    """
    if not profile_code.startswith("PROFILE_ACCEPTED_"):
        return "PROFILE_UNVERIFIED", 0, 0
    payload = source.get("multidim_event_json")
    try:
        normalized = normalize_multidim_event_payload(payload)
    except (TypeError, ValueError, RecursionError, OverflowError):
        return "PROFILE_UNVERIFIED", 0, 0
    all_ids = linked = any_rows = rows_in_event_blocks = 0
    for block in normalized:
        ids = {event["event_id"] for event in block["Event"]}
        all_ids += len(ids)
        evidence_rows = block["evidence_snippets"]
        any_rows += len(evidence_rows)
        # Evidence in a different, Event-free block cannot make an
        # Event-bearing block appear to have attributable snippet rows.
        if ids:
            rows_in_event_blocks += len(evidence_rows)
        covered = set()
        for item in evidence_rows:
            if (isinstance(item.get("text"), str) and item["text"].strip()
                    and isinstance(item.get("event_ids"), list)):
                covered.update(x for x in item["event_ids"] if x in ids)
        linked += len(covered)
    if not all_ids:
        return ("NO_EVENTS_WITH_EVIDENCE_ROWS" if any_rows else "NO_EVENTS_NO_EVIDENCE"), 0, 0
    if not rows_in_event_blocks:
        return "EVENTS_WITHOUT_EVIDENCE", all_ids, 0
    if not linked:
        return "EVENTS_WITH_ROWS_NO_ATTRIBUTABLE_TEXT", all_ids, 0
    if linked < all_ids:
        return "EVENTS_PARTIALLY_REFERENCED", all_ids, linked
    return "EVENTS_ALL_REFERENCED", all_ids, linked


INDEX = "news_test"
MAX_SAMPLE = 300
EMPTY_CHECK = {
    "full_path": "multidim_event_json",
    "validator": "multidim_event_time",
    "allow_empty_events": True,
    "min_valid_count": 1,
}


def summarize_structured_sample(total: int, candidates: int, hits: Any) -> dict:
    """Fail closed on malformed/broad data; no incomplete partial counters."""
    if (type(total) is not int or type(candidates) is not int
            or candidates < 0 or total < candidates
            or not isinstance(hits, list) or len(hits) > MAX_SAMPLE
            or len(hits) > candidates):
        raise ValueError("UNVERIFIED_SAMPLE")
    profile = Counter({key: 0 for key in PROFILE_CODES})
    time = Counter({key: 0 for key in TIME_CODES})
    empty_eligible = 0
    evidence_counts = Counter({key: 0 for key in EVIDENCE_COVERAGE_CODES})
    observed_event_ids = 0
    event_ids_with_text_references = 0
    seen = set()
    for hit in hits:
        if not isinstance(hit, dict) or hit.get("_index") != INDEX:
            raise ValueError("UNVERIFIED_SAMPLE")
        ident = hit.get("_id")
        source = hit.get("_source")
        if (not isinstance(ident, str) or not ident or ident in seen
                or not isinstance(source, dict)):
            raise ValueError("UNVERIFIED_SAMPLE")
        seen.add(ident)
        p = classify_stored_profile(source)
        t = classify_stored_document(source)
        profile[p] += 1
        time[t] += 1
        coverage, total_events, covered_events = _evidence_coverage(source, p)
        evidence_counts[coverage] += 1
        observed_event_ids += total_events
        event_ids_with_text_references += covered_events
        if p == "PROFILE_ACCEPTED_NO_EVENTS":
            if evaluate_required_output_checks(source, [EMPTY_CHECK])[0]:
                empty_eligible += 1
    return {
        "status": "OBSERVED_SAMPLE_NOT_PROVEN",
        "index": INDEX,
        "read_only": True,
        "no_writeback_or_replay": True,
        "sample_scope": "NESTED_MULTIDIM_PATH_MATCH_NOT_ALL_DOCUMENTS",
        "full_index_document_count": total,
        "nested_candidate_document_count": candidates,
        "sampled_candidate_count": len(hits),
        "sample_method": "random_score_seq_no_seed",
        "profile_counts": {key: profile[key] for key in PROFILE_CODES},
        "time_counts": {key: time[key] for key in sorted(TIME_CODES)},
        "profile_accepted_no_events_and_task_guard_eligible": empty_eligible,
        "evidence_reference_counts": {
            key: evidence_counts[key] for key in EVIDENCE_COVERAGE_CODES
        },
        "profile_accepted_event_ids_observed": observed_event_ids,
        "event_ids_with_nonempty_text_references": event_ids_with_text_references,
        "evidence_reference_scope": "BLOCK_LOCAL_IDS_ONLY_NOT_SOURCE_VERIFIED",
        "effective_runtime_rerun": "NOT_EVALUATED",
        "source_date_fidelity": "NOT_VERIFIED",
        "actual_es_mapping": "NOT_EVALUATED",
        "raw_documents_exported": False,
    }
