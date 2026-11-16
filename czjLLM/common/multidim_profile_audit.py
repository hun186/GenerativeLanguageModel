"""Read-only aggregate checks of already-stored multidim ES output.

This is NOT a rerun decision, semantic source-verification step, or a live
Elasticsearch sink readback. The existing output profile is the only schema
authority. Never return input values, document identifiers, or exception text.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from czjLLM.es_mode.output_profiles.multidim_event import (
    normalize_multidim_event_payload,
)

CATEGORIES = (
    "SOURCE_UNVERIFIED",
    "OUTPUT_ABSENT",
    "PROFILE_REJECTED",
    "PROFILE_ACCEPTED_NO_EVENTS",
    "PROFILE_ACCEPTED_MIXED_EVENT_PRESENCE",
    "PROFILE_ACCEPTED_EVENT_DATE_EMPTY_TIMELINE",
    "PROFILE_ACCEPTED_EVENT_AND_TIMELINE_DATES",
    "PROFILE_ACCEPTED_TIMELINE_DATE_ONLY",
    "PROFILE_ACCEPTED_EVENT_DATE_OTHER",
    "PROFILE_ACCEPTED_DATE_UNKNOWN",
)
MAX_DOCUMENTS = 20_000
_MISSING = object()


def classify_stored_profile(source: Any) -> str:
    """Classify one saved source without changing it or disclosing its text."""
    if not isinstance(source, dict):
        return "SOURCE_UNVERIFIED"
    if "_source" in source:
        source = source["_source"]
        if not isinstance(source, dict):
            return "SOURCE_UNVERIFIED"

    payload = source.get("multidim_event_json", _MISSING)
    if payload is _MISSING or payload is None or payload == []:
        return "OUTPUT_ABSENT"
    try:
        normalized = normalize_multidim_event_payload(payload)
    except (TypeError, ValueError, RecursionError, OverflowError):
        # The Profile may interpolate sensitive input in exception messages;
        # never expose or group messages by their contents.
        return "PROFILE_REJECTED"

    # Distinguish every block having no Event from mixed blocks. The
    # Output Profile may accept either structure, but a mixed document must
    # not inflate the "no events" count or imply the task rerun guard passes.
    if not normalized or all(not item["Event"] for item in normalized):
        return "PROFILE_ACCEPTED_NO_EVENTS"
    if any(not item["Event"] for item in normalized):
        return "PROFILE_ACCEPTED_MIXED_EVENT_PRESENCE"

    event_dated = any(
        event["time_iso"] is not None
        for item in normalized for event in item["Event"]
    )
    timeline_dated = any(
        row["time_iso"] is not None
        for item in normalized for row in item["Event_Timeline"]
    )
    if event_dated and timeline_dated:
        return "PROFILE_ACCEPTED_EVENT_AND_TIMELINE_DATES"
    if timeline_dated:
        return "PROFILE_ACCEPTED_TIMELINE_DATE_ONLY"
    if event_dated:
        explicitly_empty = (
            isinstance(payload, list)
            and all(
                isinstance(item, dict) and "Event_Timeline" in item
                and item["Event_Timeline"] == []
                for item in payload
            )
        )
        return (
            "PROFILE_ACCEPTED_EVENT_DATE_EMPTY_TIMELINE"
            if explicitly_empty else "PROFILE_ACCEPTED_EVENT_DATE_OTHER"
        )
    return "PROFILE_ACCEPTED_DATE_UNKNOWN"


def summarize_stored_profiles(sources: Iterable[Any]) -> dict:
    counts: Counter[str] = Counter()
    total = 0
    for source in sources:
        total += 1
        if total > MAX_DOCUMENTS:
            raise ValueError("DOCUMENT_BUDGET_EXCEEDED")
        counts[classify_stored_profile(source)] += 1
    if not total:
        raise ValueError("EMPTY_EXPORT")
    return {
        "schema_version": 1,
        "status": "OBSERVED_NOT_PROVEN",
        "profile": "multidim_event",
        "field": "multidim_event_json",
        "total_documents": total,
        "counts": {name: counts[name] for name in CATEGORIES},
        "source_date_fidelity": "NOT_VERIFIED",
        "actual_rerun_policy": "NOT_EVALUATED",
        "sink_writeback": "NOT_PERFORMED",
        "privacy": "FIXED_AGGREGATES_ONLY",
        "safety": "READ_ONLY_NO_ES_NO_LLM_NO_REPLAY",
    }
