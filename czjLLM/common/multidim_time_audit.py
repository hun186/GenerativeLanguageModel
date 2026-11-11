"""Offline, aggregate-only classification of *already stored* event time fields.

No rerun policy change. A blank Timeline and dated Event can be structurally
valid; an undated Event does not prove its source article lacked dates.
"""
from __future__ import annotations

import json
from collections import Counter

from czjLLM.es_mode.output_profiles.multidim_event import _validate_time_fields

CODES = frozenset({
    "EVENT_DATE_EMPTY_TIMELINE",
    "EVENT_AND_TIMELINE_DATES",
    "EVENT_DATE_OTHER_TIMELINE",
    "TIMELINE_DATE_ONLY",
    "NO_RELIABLE_DATE",
    "INVALID_TIME_FIELDS",
    "UNVERIFIED_STRUCTURE",
})


def _time_state(row):
    if not isinstance(row, dict):
        return "invalid"
    if not {"time_iso", "time_raw", "time_precision"}.issubset(row):
        return "unverified"
    try:
        # Use exactly the accepted output-profile contract, on a COPY.
        _validate_time_fields(dict(row), "redacted")
    except (ValueError, TypeError):
        return "invalid"
    if row["time_iso"] is not None:
        return "dated"
    if row["time_precision"] == "unknown":
        return "unknown"
    return "undated"


def classify_stored_document(source):
    """Return one fixed status, never raw text, IDs, dates or exception data.

    Historical ES _source may contain one article object or a list of
    article blocks. This is a triage lens, not full schema validation.
    """
    if not isinstance(source, dict):
        return "UNVERIFIED_STRUCTURE"
    body = source.get("_source", source)
    if not isinstance(body, dict):
        return "UNVERIFIED_STRUCTURE"
    payload = body.get("multidim_event_json")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            return "UNVERIFIED_STRUCTURE"
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list) or not payload:
        return "UNVERIFIED_STRUCTURE"

    event_states = []
    timeline_states = []
    all_timelines_empty = True
    for block in payload:
        if not isinstance(block, dict):
            return "UNVERIFIED_STRUCTURE"
        events = block.get("Event")
        timelines = block.get("Event_Timeline")
        if not isinstance(events, list) or not isinstance(timelines, list):
            return "UNVERIFIED_STRUCTURE"
        if timelines:
            all_timelines_empty = False
        event_states.extend(_time_state(e) for e in events)
        timeline_states.extend(_time_state(e) for e in timelines)

    if "invalid" in event_states or "invalid" in timeline_states:
        return "INVALID_TIME_FIELDS"
    if "unverified" in event_states or "unverified" in timeline_states:
        return "UNVERIFIED_STRUCTURE"
    event_dated = "dated" in event_states
    timeline_dated = "dated" in timeline_states
    if event_dated and all_timelines_empty:
        return "EVENT_DATE_EMPTY_TIMELINE"
    if event_dated and timeline_dated:
        return "EVENT_AND_TIMELINE_DATES"
    if event_dated:
        return "EVENT_DATE_OTHER_TIMELINE"
    if timeline_dated:
        return "TIMELINE_DATE_ONLY"
    return "NO_RELIABLE_DATE"


def summarize_stored_documents(sources):
    """Aggregate only; never attach document excerpts to the result."""
    counts = Counter({name: 0 for name in CODES})
    total = 0
    for source in sources:
        if total >= 20_000:
            raise ValueError("DOCUMENT_LIMIT")
        code = classify_stored_document(source)
        counts[code] += 1
        total += 1
    return {
        "schema_version": 1,
        "status": "OBSERVED_NOT_PROVEN",
        "total_documents": total,
        "counts": {name: counts[name] for name in sorted(CODES)},
        "legacy_timeline_only_false_rerun_candidates": counts[
            "EVENT_DATE_EMPTY_TIMELINE"
        ],
        "source_date_fidelity": "NOT_VERIFIED",
        "actual_rerun_policy": "NOT_CHANGED_OR_EVALUATED",
        "sink_writeback": "NOT_PERFORMED",
        "safety": "READ_ONLY_NO_ES_NO_LLM_NO_REPLAY",
    }
