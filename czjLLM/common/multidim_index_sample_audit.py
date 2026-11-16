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
        "effective_runtime_rerun": "NOT_EVALUATED",
        "source_date_fidelity": "NOT_VERIFIED",
        "actual_es_mapping": "NOT_EVALUATED",
        "raw_documents_exported": False,
    }
