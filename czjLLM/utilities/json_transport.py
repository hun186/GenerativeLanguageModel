"""Remove only proven outer JSON transport wrappers, never payload markers.

This is not a JSON repair or schema validator. Malformed or ambiguous
responses retain their original characters for the existing retry path.
"""
from __future__ import annotations

import json
import re

_WS = " \t\r\n"
_THINK_PREFIX = re.compile(r"\A[ \t\r\n]*<think>.*?</think>", re.DOTALL)
_FENCE = re.compile(
    r"\A\x60\x60\x60(?:json)?[ \t]*\r?\n(.*?)\r?\n[ \t]*\x60\x60\x60\Z",
    re.IGNORECASE | re.DOTALL,
)


def is_json_output_task(task: str) -> bool:
    normalized = (task or "").strip().lower()
    return "to json" in normalized or normalized == "json format repair"


def clean_json_transport(raw: str, *, include_think: bool = False) -> str:
    """Keep internal backticks and think tags verbatim.

    Only remove a complete outer fence or leading thinking block when the
    remaining body parses as a complete JSON value. The existing JSON and
    output-contract validation still runs downstream. Incomplete responses
    must never be treated as accepted by this preprocessing step.
    """
    stripped = raw.strip(_WS)
    if stripped.replace(" ", "").replace("\n", "") == "<EMPTY>":
        return ""
    candidate = stripped
    if not include_think:
        thinking = _THINK_PREFIX.match(candidate)
        if thinking:
            candidate = candidate[thinking.end():].strip(_WS)
            if candidate.replace(" ", "").replace("\n", "") == "<EMPTY>":
                return ""
    fence = _FENCE.fullmatch(candidate)
    if fence:
        candidate = fence.group(1).strip(_WS)
    # No global substitutions, including for already valid JSON.
    if candidate == raw:
        return raw
    try:
        json.loads(candidate)
    except (ValueError, RecursionError, OverflowError):
        return raw
    return candidate
