"""Pure shared evaluator for configured ES rerun required-output checks.

This evaluates an already assembled source/output document, never a single
intermediate LLM slice. Reporting is payload-free and does not choose a retry
or writeback policy.
"""
from __future__ import annotations

from czjLLM.common.multidim_time_audit import classify_stored_document
from czjLLM.es_mode.adapters.value_helpers import (
    deep_collect_by_path, flatten_list, is_non_empty_deep,
    is_valid_date_string,
)


def evaluate_required_output_checks(source: dict, checks: list[dict]) -> tuple[bool, dict | None]:
    """Return (passed, first failure metadata) using existing rerun semantics.

    Each check must have a previously resolved full_path from
    ElasticsearchPendingPolicyMixin._get_required_output_checks().
    """
    for check in checks:
        path = check["full_path"]
        validator = (check.get("validator") or "non_empty").lower()
        fmt = check.get("format")
        minimum = int(check.get("min_valid_count", 1))
        values = flatten_list(deep_collect_by_path(source, path))
        count = 0
        if validator == "multidim_event_time":
            # Entire multidim_event_json output is the validation unit, not
            # a single non-null date. Reuse the accepted output-profile time
            # checks via the existing read-only audit classifier. No LLM call.
            # All article blocks must contain a core Event; a Timeline-only
            # record cannot satisfy the SRAF core-event requirement.
            events_present = bool(values) and all(
                isinstance(block, dict)
                and isinstance(block.get("Event"), list)
                and bool(block["Event"])
                and all(
                    isinstance(event, dict)
                    and isinstance(event.get("event_id"), str)
                    and bool(event["event_id"].strip())
                    for event in block["Event"]
                )
                and len({event["event_id"].strip() for event in block["Event"]})
                == len(block["Event"])
                for block in values
            )
            if events_present:
                state = classify_stored_document({"multidim_event_json": values})
                # For a null ISO date, the explicit unknown marker is valid.
                # A known *partial* time can also have a null ISO date if it
                # retains its original raw time. But a null date and null raw
                # time with a supposedly known precision is inconsistent.
                no_unmarked_missing = all(
                    row.get("time_iso") is not None
                    or row.get("time_precision") == "unknown"
                    or (isinstance(row.get("time_raw"), str)
                        and bool(row["time_raw"].strip()))
                    for block in values
                    for field in ("Event", "Event_Timeline")
                    for row in block[field]
                ) if state not in {"INVALID_TIME_FIELDS", "UNVERIFIED_STRUCTURE"} else False
                if no_unmarked_missing:
                    # NO_RELIABLE_DATE remains a structurally valid unknown;
                    # this does not prove the source article lacks a date.
                    count = 1
        else:
            for value in values:
                valid = (is_valid_date_string(value, fmt or "yyyy-MM-dd")
                         if validator == "date" else is_non_empty_deep(value))
                if valid:
                    count += 1
                if count >= minimum:
                    break
        if count < minimum:
            return False, {
                "path": path, "validator": validator, "format": fmt,
                "found_valid": count, "min_valid_count": minimum,
            }
    return True, None
