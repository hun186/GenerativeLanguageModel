"""Read-only hypothetical time-rule comparison for Issue #293.

This module does NOT evaluate effective operator rerun settings, sink freshness,
article evidence, per-document success, or write to Elasticsearch. It compares
only a historical Timeline-min-1 check against the proposed *time-only* triage.
"""
from __future__ import annotations

from collections import Counter
import json

from czjLLM.common.multidim_time_audit import classify_stored_document
from czjLLM.common.required_output_guard import evaluate_required_output_checks

_DATE_PRESENT = frozenset({
    "EVENT_DATE_EMPTY_TIMELINE",
    "EVENT_AND_TIMELINE_DATES",
    "EVENT_DATE_OTHER_TIMELINE",
    "TIMELINE_DATE_ONLY",
})
_TIME_UNKNOWN = "NO_RELIABLE_DATE"
_INVALID = frozenset({"INVALID_TIME_FIELDS", "UNVERIFIED_STRUCTURE"})
_LEGACY_CHECKS = ({
    "full_path": "multidim_event_json.Event_Timeline.time_iso",
    "validator": "date",
    "format": "iso8601",
    "min_valid_count": 1,
},)
_MAX_ITEMS = 20_000


def _source_body(record):
    if not isinstance(record, dict):
        return None
    body = record.get("_source", record)
    if not isinstance(body, dict):
        return None
    payload = body.get("multidim_event_json")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            return None
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list) or not payload:
        return None
    return {"multidim_event_json": payload}


def summarize_hypothetical_time_rules(records):
    """Aggregate only; raw record fields, IDs and dates never enter results.

    All structurally invalid/unverified outputs count as INDETERMINATE,
    regardless of whether the legacy Timeline date check happened to pass.
    """
    counts = Counter({
        "legacy_timeline_min_1_pass": 0,
        "legacy_timeline_min_1_fail": 0,
        "legacy_time_rule_indeterminate": 0,
        "proposed_date_present": 0,
        "proposed_date_unknown_requires_source_review": 0,
        "proposed_invalid_or_unverified_requires_review": 0,
        "legacy_fail_but_proposed_date_present": 0,
        "legacy_fail_but_proposed_time_unknown": 0,
        "legacy_pass_but_proposed_invalid_or_unverified": 0,
    })
    total = 0
    for record in records:
        if total >= _MAX_ITEMS:
            raise ValueError("DOCUMENT_LIMIT")
        total += 1
        quality = classify_stored_document(record)
        body = _source_body(record)
        if quality in _INVALID or body is None:
            counts["proposed_invalid_or_unverified_requires_review"] += 1
            counts["legacy_time_rule_indeterminate"] += 1
            # Even if the raw Timeline check could pass, this is not a valid
            # old output. Do not mix uncertain structural cases with safe delta.
            continue
        if quality in _DATE_PRESENT:
            counts["proposed_date_present"] += 1
        elif quality == _TIME_UNKNOWN:
            counts["proposed_date_unknown_requires_source_review"] += 1
        else:
            # Fail closed if future classifier adds an unfamiliar state.
            counts["proposed_invalid_or_unverified_requires_review"] += 1
            counts["legacy_time_rule_indeterminate"] += 1
            continue
        passed, _ = evaluate_required_output_checks(body, list(_LEGACY_CHECKS))
        if passed:
            counts["legacy_timeline_min_1_pass"] += 1
        else:
            counts["legacy_timeline_min_1_fail"] += 1
            if quality in _DATE_PRESENT:
                counts["legacy_fail_but_proposed_date_present"] += 1
            else:
                counts["legacy_fail_but_proposed_time_unknown"] += 1

    assert (counts["proposed_date_present"]
            + counts["proposed_date_unknown_requires_source_review"]
            + counts["proposed_invalid_or_unverified_requires_review"] == total)
    assert (counts["legacy_timeline_min_1_pass"]
            + counts["legacy_timeline_min_1_fail"]
            + counts["legacy_time_rule_indeterminate"] == total)
    return {
        "schema_version": 1,
        "status": "HYPOTHETICAL_NOT_EFFECTIVE_CONFIG",
        "total_documents": total,
        "counts": {key: counts[key] for key in sorted(counts)},
        "comparison_scope": "TIME_ONLY_NOT_COMPLETE_RERUN_POLICY",
        "source_date_fidelity": "NOT_VERIFIED",
        "metadata_hash_force_rerun": "NOT_EVALUATED",
        "automatic_skip_or_replay_decision": "NOT_AUTHORIZED",
        "safety": "READ_ONLY_NO_ES_NO_LLM_NO_REPLAY",
    }
