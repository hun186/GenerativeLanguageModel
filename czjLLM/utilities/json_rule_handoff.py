"""Bounded wire format for trusted renderer-to-Worker source receipts.

Only integrity/identity binding, not authentication. The queue must supply
independently established current generation and effective task fingerprint.
Never reconstruct these from this wire record itself or the model response.
No queue writes, raw text retention, policy activation or sink authority.
"""
from __future__ import annotations

import json
import re

from czjLLM.utilities.json_rule_policy import (
    SourceSpanReceipt, verified_source_span, rebind_source_span_after_no_think,
)
from czjLLM.utilities.json_rule_repair import MAX_CHARS

MAX_HANDOFF_CHARS = 1024
_FIELDS = frozenset({
    "version", "generation_id", "task_sha256", "prompt_sha256",
    "source_sha256", "start", "end",
})


def _hex(value: object, size: int) -> bool:
    return isinstance(value, str) and len(value) == size and re.fullmatch(
        r"[0-9a-f]+", value,
    ) is not None


def _unique_pairs(pairs):
    data = {}
    for key, value in pairs:
        if key in data:
            raise ValueError("duplicate source receipt field")
        data[key] = value
    return data


def encode_source_handoff(
    rendered_prompt: str, receipt: SourceSpanReceipt,
    *, generation_id: str, task_sha256: str,
) -> str | None:
    """Trusted producer only; caller allocates a fresh generation per slice."""
    if not _hex(generation_id, 32) or not _hex(task_sha256, 64):
        return None
    if verified_source_span(rendered_prompt, receipt) is None:
        return None
    return json.dumps({
        "version": 1, "generation_id": generation_id, "task_sha256": task_sha256,
        "prompt_sha256": receipt.prompt_sha256,
        "source_sha256": receipt.source_sha256,
        "start": receipt.start, "end": receipt.end,
    }, sort_keys=True, separators=(",", ":"))


def decode_source_handoff(
    wire: str, rendered_prompt: str, *, expected_generation_id: str,
    expected_task_sha256: str,
) -> SourceSpanReceipt | None:
    """Reject unknown, missing, stale or changed metadata without guessing.

    A matching hash does not establish that a receipt was issued by a trusted
    renderer. The future transport must protect its producer/consumer boundary.
    """
    if (not isinstance(wire, str) or not 0 < len(wire) <= MAX_HANDOFF_CHARS
            or not _hex(expected_generation_id, 32)
            or not _hex(expected_task_sha256, 64)):
        return None
    try:
        data = json.loads(wire, object_pairs_hook=_unique_pairs)
        if (type(data) is not dict or set(data) != _FIELDS
                or type(data["version"]) is not int or data["version"] != 1
                or data["generation_id"] != expected_generation_id
                or data["task_sha256"] != expected_task_sha256
                or not _hex(data["prompt_sha256"], 64)
                or not _hex(data["source_sha256"], 64)
                or type(data["start"]) is not int or type(data["end"]) is not int
                or not 0 <= data["start"] < data["end"] <= MAX_CHARS):
            return None
        receipt = SourceSpanReceipt(
            data["prompt_sha256"], data["source_sha256"], data["start"], data["end"],
        )
        return receipt if verified_source_span(rendered_prompt, receipt) is not None else None
    except (ValueError, TypeError, RecursionError, OverflowError):
        return None


def bind_dispatched_source_handoff(
    wire: str, rendered_prompt: str, dispatched_prompt: str, *,
    expected_generation_id: str, expected_task_sha256: str,
) -> SourceSpanReceipt | None:
    """Verify current task/generation, then bind to actual finalized user content."""
    receipt = decode_source_handoff(
        wire, rendered_prompt, expected_generation_id=expected_generation_id,
        expected_task_sha256=expected_task_sha256,
    )
    if receipt is None:
        return None
    return rebind_source_span_after_no_think(rendered_prompt, receipt, dispatched_prompt)
