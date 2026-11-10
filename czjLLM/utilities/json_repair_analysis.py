# -*- coding: utf-8 -*-
"""Bounded payload-free diagnostics for an invalid JSON -> parseable JSON repair.

Heuristic lexical comparison, never semantic quality assurance. The caller
passes original/repaired text in memory; only scalar metrics are retained.
"""
from __future__ import annotations

from difflib import SequenceMatcher
import json
import re

MAX_ANALYSIS_CHARS = 160_000
MAX_ANALYSIS_TOKENS = 3_000
# For each string literal, preserve it as one lexical token; malformed
# unterminated trailing strings remain distinct from valid repaired literals.
_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"?|[{}\[\],:]|[^\s{}\[\],:"]+', re.DOTALL)
_KEY_PATTERN = re.compile(r'"(?:\\.|[^"\\])*"\s*:')
_PUNCT = frozenset("{}[],:")
_KINDS = frozenset({
    "JSON_REPAIR_SYNTAX_CANDIDATE",
    "JSON_REPAIR_TAIL_CANDIDATE",
    "JSON_REPAIR_CONTENT_EDIT",
    "JSON_REPAIR_LARGE_CHANGE",
    "JSON_REPAIR_COMPARISON_UNAVAILABLE",
})
_ERROR_KINDS = frozenset({
    "UNTERMINATED_STRING", "EXPECTED_DELIMITER", "EXTRA_DATA",
    "INVALID_ESCAPE", "OTHER",
})
_MAX_METRIC = 1_000_000
_METRIC_KEYS = frozenset({
    "original_chars", "repaired_chars", "common_prefix_chars",
    "common_suffix_chars", "same_literal_pct", "before_key_patterns",
    "after_key_patterns", "error_pos_pct",
})


def _error_kind(error: json.JSONDecodeError) -> str:
    reason = error.msg.lower()
    if "unterminated string" in reason:
        return "UNTERMINATED_STRING"
    if "delimiter" in reason or "expecting" in reason:
        return "EXPECTED_DELIMITER"
    if "extra data" in reason:
        return "EXTRA_DATA"
    if "escape" in reason or "control character" in reason:
        return "INVALID_ESCAPE"
    return "OTHER"


def validate_repair_detail(detail: object) -> bool:
    """Strict event boundary: no arbitrary keys, values or document strings."""
    if not isinstance(detail, dict) or set(detail) != _METRIC_KEYS | {"error_kind"}:
        return False
    if not isinstance(detail.get("error_kind"), str) or detail["error_kind"] not in _ERROR_KINDS:
        return False
    for key in _METRIC_KEYS:
        value = detail.get(key)
        if type(value) is not int or not (0 <= value <= _MAX_METRIC):
            return False
    if detail["same_literal_pct"] > 100 or detail["error_pos_pct"] > 100:
        return False
    if detail["common_prefix_chars"] > min(detail["original_chars"], detail["repaired_chars"]):
        return False
    if detail["common_suffix_chars"] > min(detail["original_chars"], detail["repaired_chars"]):
        return False
    return True


def analyze_json_repair(original: str, repaired: str,
                        error: json.JSONDecodeError) -> tuple[str, dict]:
    """Classify lexical changes to already-parseable repaired JSON.

    We do not claim that changed JSON preserves meaning, arrays, entity links,
    or all events. Large/complex inputs fail closed to 'comparison unavailable'.
    No original or repaired tokens are returned or persisted.
    """
    if not isinstance(original, str) or not isinstance(repaired, str):
        raise TypeError("JSON repair comparison requires strings")
    if not isinstance(error, json.JSONDecodeError):
        raise TypeError("original parse error is required")
    original_size, repaired_size = len(original), len(repaired)
    limit = min(original_size, repaired_size)
    prefix = 0
    while prefix < limit and original[prefix] == repaired[prefix]:
        prefix += 1
    suffix = 0
    while (suffix < limit - prefix
           and original[original_size - 1 - suffix] == repaired[repaired_size - 1 - suffix]):
        suffix += 1
    metrics = {
        "original_chars": min(_MAX_METRIC, original_size),
        "repaired_chars": min(_MAX_METRIC, repaired_size),
        "common_prefix_chars": min(_MAX_METRIC, prefix),
        "common_suffix_chars": min(_MAX_METRIC, suffix),
        "before_key_patterns": 0,
        "after_key_patterns": 0,
        "same_literal_pct": 0,
        "error_kind": _error_kind(error),
        "error_pos_pct": min(100, round(100 * error.pos / max(1, original_size))),
    }
    if original_size > MAX_ANALYSIS_CHARS or repaired_size > MAX_ANALYSIS_CHARS:
        return "JSON_REPAIR_COMPARISON_UNAVAILABLE", metrics

    metrics["before_key_patterns"] = len(_KEY_PATTERN.findall(original))
    metrics["after_key_patterns"] = len(_KEY_PATTERN.findall(repaired))
    if (metrics["before_key_patterns"] > _MAX_METRIC or
            metrics["after_key_patterns"] > _MAX_METRIC):
        return "JSON_REPAIR_COMPARISON_UNAVAILABLE", metrics
    before_tokens = _TOKEN.findall(original)
    after_tokens = _TOKEN.findall(repaired)
    if (len(before_tokens) > MAX_ANALYSIS_TOKENS or
            len(after_tokens) > MAX_ANALYSIS_TOKENS):
        return "JSON_REPAIR_COMPARISON_UNAVAILABLE", metrics
    before_literals = [x for x in before_tokens if x not in _PUNCT]
    after_literals = [x for x in after_tokens if x not in _PUNCT]
    same = before_literals == after_literals
    if same:
        metrics["same_literal_pct"] = 100
        return "JSON_REPAIR_SYNTAX_CANDIDATE", metrics

    # An almost entirely matching prefix ending in an unterminated string
    # suggests a tail completion. It can still omit/alter source facts.
    if (metrics["error_kind"] == "UNTERMINATED_STRING"
            and repaired.startswith(original)
            and len(original) > 0):
        return "JSON_REPAIR_TAIL_CANDIDATE", metrics

    if not before_literals:
        return "JSON_REPAIR_COMPARISON_UNAVAILABLE", metrics
    matcher = SequenceMatcher(None, before_literals, after_literals, autojunk=True)
    matching_chars = sum(
        len(x) for i, _j, size in matcher.get_matching_blocks()
        for x in before_literals[i:i+size]
    )
    total_chars = sum(map(len, before_literals))
    similarity = min(100, round(100 * matching_chars / max(1, total_chars)))
    metrics["same_literal_pct"] = similarity
    if similarity < 70 or (
        abs(repaired_size - original_size) > max(80, original_size * 0.35)
        and similarity < 95
    ):
        return "JSON_REPAIR_LARGE_CHANGE", metrics
    return "JSON_REPAIR_CONTENT_EDIT", metrics
