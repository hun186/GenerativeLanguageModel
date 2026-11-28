"""Numeric-only JSON repair diagnostics. Never reads original/repaired payloads."""
from czjLLM.utilities.json_repair_analysis import _KINDS, _ERROR_KINDS, validate_repair_detail

RECENT_LIMIT = 50
_LITERAL_CLASSES = frozenset({"JSON_REPAIR_SYNTAX_CANDIDATE",
                              "JSON_REPAIR_CONTENT_EDIT", "JSON_REPAIR_LARGE_CHANGE"})
_UNAVAILABLE = "JSON_REPAIR_COMPARISON_UNAVAILABLE"


def _count(value):
    if type(value) is not int or not 0 <= value <= (1 << 53) - 1:
        raise ValueError("invalid repair count")
    return value


def _pct(n, d):
    return round(100 * n / d, 2) if d else None


def _distribution(values):
    if not values:
        return {"count": 0, "min": None, "p50": None, "p95": None, "max": None}
    values = sorted(values)
    def percentile(q):
        pos = (len(values) - 1) * q
        lo = int(pos)
        hi = min(lo + 1, len(values) - 1)
        return round(values[lo] + (values[hi] - values[lo]) * (pos - lo), 2)
    return {"count": len(values), "min": values[0], "p50": percentile(.5),
            "p95": percentile(.95), "max": values[-1]}


def project_repair_analysis(stats):
    """Exact run counts and separately scoped recent scalar distributions."""
    try:
        success = _count(stats["repair_succeeded"])
        count = _count(stats["repair_analysis_count"])
        categories = stats["repair_analysis_categories"]
        recent = stats["repair_analysis_recent"]
        if (not isinstance(categories, dict) or set(categories) - _KINDS
                or not isinstance(recent, list) or len(recent) > RECENT_LIMIT
                or len(recent) != min(count, RECENT_LIMIT) or count > success):
            raise ValueError("invalid comparison coverage")
        counts = {key: _count(categories.get(key, 0)) for key in sorted(_KINDS)}
        if sum(counts.values()) != count:
            raise ValueError("invalid classification totals")
        recent_counts = {key: 0 for key in counts}
        errors = {key: 0 for key in sorted(_ERROR_KINDS)}
        literal, length_delta, error_pos, key_delta = [], [], [], []
        for case in recent:
            if not isinstance(case, dict):
                raise ValueError("invalid recent case")
            detail = case.get("detail")
            code = case.get("code")
            if (not validate_repair_detail(detail) or code not in counts
                    or detail.get("repair_class") != code):
                raise ValueError("invalid recent detail")
            recent_counts[code] += 1
            errors[detail["error_kind"]] += 1
            error_pos.append(detail["error_pos_pct"])
            # The lexical producer deliberately emits zero placeholders for
            # unavailable and tail-only comparisons. Those are not measured
            # literal similarity. Key counts are unavailable in that class.
            if code in _LITERAL_CLASSES:
                literal.append(detail["same_literal_pct"])
            if code != _UNAVAILABLE:
                length_delta.append(detail["repaired_chars"] - detail["original_chars"])
                key_delta.append(detail["after_key_patterns"] - detail["before_key_patterns"])
        if any(recent_counts[k] > counts[k] for k in counts):
            raise ValueError("recent classification exceeds run counts")
        comparable = count - counts[_UNAVAILABLE]
        return {
            "status": "observed" if count else "no_comparison",
            "scope": "all_observed_successful_repairs",
            "successful_repairs": success, "classified_rows": count,
            "unreported_rows": success - count,
            "comparable_rows": comparable,
            "classification_coverage_pct": _pct(count, success),
            "comparable_coverage_pct": _pct(comparable, success),
            "categories": counts,
            "recent": {"scope": "latest_classified_success_events",
                       "limit": RECENT_LIMIT, "count": len(recent),
                       "error_kinds": errors, "categories": recent_counts,
                       "metrics": {
                           "same_literal_pct": _distribution(literal),
                           "length_delta_chars": _distribution(length_delta),
                           "key_pattern_delta": _distribution(key_delta),
                           "error_pos_pct": _distribution(error_pos),
                       }},
            "semantic_preservation_verified": False,
        }
    except (KeyError, TypeError, ValueError, OverflowError):
        return {"status": "unverified"}
