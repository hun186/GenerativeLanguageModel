"""Pure opt-in policy and candidate gate; not wired to live Workers.

A source receipt must originate at trusted prompt generation, not from a
heuristic parser or the model response. Hashes bind an already trusted span;
they do not confer authority on arbitrary caller-supplied source text.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256

from czjLLM.utilities.json_rule_repair import (
    MAX_CHARS, RepairCandidate, repair_generic_json,
    repair_multidim_evidence_quotes,
)


@dataclass(frozen=True)
class JsonRepairPolicy:
    generic: bool = False
    multidim_evidence_quotes: bool = False


def parse_json_repair_policy(task_spec: Mapping | None) -> JsonRepairPolicy:
    """Read the effective task's own explicit policy; never infer from its name."""
    if task_spec is None:
        return JsonRepairPolicy()
    if not isinstance(task_spec, Mapping):
        raise ValueError("invalid task specification")
    if "json_rule_repair" not in task_spec:
        return JsonRepairPolicy()
    value = task_spec["json_rule_repair"]
    keys = {"generic", "multidim_evidence_quotes"}
    if not isinstance(value, Mapping) or set(value) - keys:
        raise ValueError("invalid json_rule_repair policy")
    if any(type(flag) is not bool for flag in value.values()):
        raise ValueError("json_rule_repair flags must be booleans")
    return JsonRepairPolicy(**dict(value))


def _digest(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SourceSpanReceipt:
    prompt_sha256: str
    source_sha256: str
    start: int
    end: int


def create_source_span_receipt(
    prompt: str, source: str, start: int,
) -> SourceSpanReceipt:
    """Trusted renderer records its exact inserted span; no searching or guessing."""
    if (not isinstance(prompt, str) or not isinstance(source, str)
            or not source or len(source) > MAX_CHARS
            or len(prompt) > MAX_CHARS or type(start) is not int or start < 0
            or prompt[start:start + len(source)] != source):
        raise ValueError("unverified source span")
    return SourceSpanReceipt(_digest(prompt), _digest(source), start, start + len(source))


def verified_source_span(prompt: str, receipt: SourceSpanReceipt | None) -> str | None:
    """Validate against the exact dispatched prompt without logging or persisting text."""
    if (not isinstance(receipt, SourceSpanReceipt) or not isinstance(prompt, str)
            or len(prompt) > MAX_CHARS or type(receipt.start) is not int
            or type(receipt.end) is not int
            or not 0 <= receipt.start < receipt.end <= len(prompt)):
        return None
    try:
        if _digest(prompt) != receipt.prompt_sha256:
            return None
        source = prompt[receipt.start:receipt.end]
        return source if _digest(source) == receipt.source_sha256 else None
    except UnicodeError:
        return None


def select_rule_candidate(
    raw: str, *, policy: JsonRepairPolicy, finish_reason: str,
    validate_candidate: Callable[[str], bool],
    dispatched_prompt: str = "", source_receipt: SourceSpanReceipt | None = None,
) -> RepairCandidate | None:
    """Return a validated candidate only; caller retains original on all refusals.

    The validator must represent the caller's actual applicable output contract.
    No default validator and no acceptance for unconfirmed provider completion.
    This function neither calls the LLM nor authorizes a write.
    """
    if (finish_reason != "stop" or not isinstance(policy, JsonRepairPolicy)
            or type(policy.generic) is not bool
            or type(policy.multidim_evidence_quotes) is not bool):
        return None
    try:
        generic = repair_generic_json(raw) if policy.generic else None
        source = (verified_source_span(dispatched_prompt, source_receipt)
                  if policy.multidim_evidence_quotes else None)
        specific = repair_multidim_evidence_quotes(raw, source) if source else None
        if generic and specific and generic.text != specific.text:
            return None
        candidate = generic or specific
        if candidate is None or validate_candidate(candidate.text) is not True:
            return None
        return candidate
    except Exception:
        # Diagnostic/contract failures must not turn a candidate into output.
        return None
