"""Bounded read-only coverage of existing LLM audit correlation fields.

Each observed CSV row is one logged observation, never a provider HTTP attempt,
logical retry family, unique document, authenticated queue generation or
confirmed sink writeback. No raw IDs, filenames, URLs, errors or payloads leave
this module. The existing strict snapshot opener rejects unstable/linked files.
"""
from __future__ import annotations

from pathlib import Path
from uuid import UUID, RFC_4122

from czjLLM.utilities.llm_failure_summary import (
    MAX_AUDIT_FILE_BYTES, _iter_audit_csv_rows, _read_bounded_csv,
)

_ID_COLUMNS = ("audit_record_id", "worker_call_id", "queue_claim_event_id")
_OUTCOME_COLUMN = "call_llm_api_returned"


def _canonical_uuid4_hex(value: str) -> bool:
    """Audit/worker/queue IDs are canonical opaque UUID4 hex, never text IDs."""
    if len(value) != 32 or value != value.lower():
        return False
    try:
        parsed = UUID(hex=value)
    except (ValueError, AttributeError):
        return False
    return parsed.hex == value and parsed.version == 4 and parsed.variant == RFC_4122


def summarize_llm_lineage_evidence(path: str | Path) -> dict:
    """Count only present, validated audit-row correlation evidence.

    Existing legacy CSV headers remain supported. Missing columns are unknown,
    not a false zero. Duplicates/invalid IDs are surfaced as counts, never
    silently treated as distinct Worker calls or de-duplicated requests.
    """
    text, _size = _read_bounded_csv(Path(path), max_bytes=MAX_AUDIT_FILE_BYTES)
    field_limit = [128]
    source = iter(_iter_audit_csv_rows(text, field_limit=field_limit))
    header = next(source, [])
    if (len(header) != len(set(header)) or header.count("ok") != 1
            or header.count("error") != 1):
        raise ValueError("invalid audit CSV header")
    field_limit[0] = len(header)
    indexes = {key: header.index(key) if key in header else None
               for key in _ID_COLUMNS + (_OUTCOME_COLUMN,)}
    ok_index = header.index("ok")
    ids = {key: {"column_present": indexes[key] is not None,
                 "valid_rows": None if indexes[key] is None else 0,
                 "blank_rows": None if indexes[key] is None else 0,
                 "invalid_rows": None if indexes[key] is None else 0,
                 "duplicate_rows": None if indexes[key] is None else 0}
           for key in _ID_COLUMNS}
    observed = {key: set() for key in _ID_COLUMNS}
    total = malformed = yes = no = unknown_outcome = 0
    returned = {"column_present": indexes[_OUTCOME_COLUMN] is not None,
                "yes_rows": None if indexes[_OUTCOME_COLUMN] is None else 0,
                "no_rows": None if indexes[_OUTCOME_COLUMN] is None else 0,
                "unknown_rows": None if indexes[_OUTCOME_COLUMN] is None else 0,
                "invalid_rows": None if indexes[_OUTCOME_COLUMN] is None else 0}
    claim_without_worker = None if indexes["queue_claim_event_id"] is None or indexes["worker_call_id"] is None else 0
    for row in source:
        total += 1
        if len(row) != len(header):
            malformed += 1
            continue
        status = row[ok_index]
        if status == "YES":
            yes += 1
        elif status == "NO":
            no += 1
        else:
            unknown_outcome += 1
        for name in _ID_COLUMNS:
            index = indexes[name]
            if index is None:
                continue
            value = row[index]
            if not value:
                ids[name]["blank_rows"] += 1
            elif not _canonical_uuid4_hex(value):
                ids[name]["invalid_rows"] += 1
            else:
                ids[name]["valid_rows"] += 1
                if value in observed[name]:
                    ids[name]["duplicate_rows"] += 1
                else:
                    observed[name].add(value)
        if claim_without_worker is not None:
            if row[indexes["queue_claim_event_id"]] and not row[indexes["worker_call_id"]]:
                claim_without_worker += 1
        index = indexes[_OUTCOME_COLUMN]
        if index is not None:
            value = row[index]
            if value == "YES":
                returned["yes_rows"] += 1
            elif value == "NO":
                returned["no_rows"] += 1
            elif value == "":
                # Direct/legacy/stage calls need not provide this Worker marker.
                returned["unknown_rows"] += 1
            else:
                returned["invalid_rows"] += 1

    # A claim may legitimately be referenced by more than one audit row;
    # it is not an attempt UUID. Likewise a Worker may have multiple
    # observations. Only audit_record_id promises one ID per *CSV row*.
    degraded = (
        malformed > 0 or unknown_outcome > 0
        or any((ids[name]["invalid_rows"] or 0) > 0 for name in _ID_COLUMNS)
        or (ids["audit_record_id"]["duplicate_rows"] or 0) > 0
        or (claim_without_worker or 0) > 0
        or (returned["invalid_rows"] or 0) > 0
    )
    gaps = (any(not item["column_present"] or item["blank_rows"]
                for item in ids.values())
            or not returned["column_present"]
            or (returned["unknown_rows"] or 0) > 0)
    state = ("no_rows" if not total else "degraded" if degraded
             else "partial_evidence" if gaps else "observed")
    return {
        "report_version": 1,
        "scope": "one_audit_csv",
        "state": state,
        "observed_csv_rows": total,
        "malformed_width_rows": malformed,
        "observed_yes_rows": yes,
        "observed_no_rows": no,
        "unknown_outcome_rows": unknown_outcome,
        "audit_id_columns": ids,
        "duplicate_id_semantics": (
            "audit_record_id duplicates violate per-row uniqueness; "
            "worker_call_id and queue_claim_event_id repeats are counted "
            "as shared references, not automatically treated as errors"
        ),
        "call_llm_api_returned": returned,
        "claim_id_without_worker_call_id_rows": claim_without_worker,
        "denominator_contract": (
            "CSV row evidence only; not provider HTTP attempt, SDK retry, "
            "logical retry family, unique source document, authenticated "
            "queue generation, or confirmed SQL/ES sink writeback"
        ),
        "evidence_limits": (
            "An audit may be missing before/after a Worker call; a queue claim "
            "receipt on a row was verified at its Worker call site but is not "
            "independently re-verified by this offline CSV report. "
            "Missing columns, IDs and outcomes remain unknown."
        ),
    }
