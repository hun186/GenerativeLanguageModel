"""Bounded, non-payload change-bar segments for repair review windows."""
from __future__ import annotations


def change_map_segments(case: dict) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Known equal prefixes/suffixes and unverified middle, not a semantic diff."""
    detail = case.get("detail") or {}
    a = max(0, int(detail.get("original_chars", 0)))
    b = max(0, int(detail.get("repaired_chars", 0)))
    prefix = min(a, b, max(0, int(detail.get("common_prefix_chars", 0))))
    suffix = min(a - prefix, b - prefix,
                 max(0, int(detail.get("common_suffix_chars", 0))))
    return ((prefix, a - prefix - suffix, suffix),
            (prefix, b - prefix - suffix, suffix))
