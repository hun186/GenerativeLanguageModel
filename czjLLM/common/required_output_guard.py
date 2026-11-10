"""Pure shared evaluator for configured ES rerun required-output checks.

This evaluates an already assembled source/output document, never a single
intermediate LLM slice. Reporting is payload-free and does not choose a retry
or writeback policy.
"""
from __future__ import annotations

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
