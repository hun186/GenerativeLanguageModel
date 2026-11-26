"""Resolve explicit, trusted legacy named-task repair contracts.

No task-name inference, YAML import strings, alias inheritance, or document
required-output checks. Missing, conflicting or unsupported config stays off.
Only the legacy single-stage Consumer opts in via this module.
"""
from __future__ import annotations

from collections.abc import Mapping
import inspect
import json
import pickle

from czjLLM.prompt_pipeline.task_fingerprint import fingerprint_task
from czjLLM.utilities.json_rule_policy import parse_json_repair_policy
from czjLLM.task_configs.taskSetting_Enrichment import TRUSTED_MULTIDIM_SOURCE_RENDERERS


def validate_multidim_event_slice(text: str) -> bool:
    """Use the existing profile as a non-mutating slice-level contract.

    Do not apply assembled-document required-output checks here, and never
    return or write the normalized value. Profile validation is structural,
    not a claim of semantic completeness or truth.
    """
    from czjLLM.es_mode.output_profiles.multidim_event import normalize_multidim_event_payload

    payload = json.loads(text)
    if not isinstance(payload, list) or not payload:
        return False
    normalize_multidim_event_payload(payload)
    return True


_CONTRACTS = {"multidim_event_slice_v1": validate_multidim_event_slice}


def _resolve_validator(value):
    if isinstance(value, str):
        return _CONTRACTS.get(value)
    # Trusted Python task settings may supply an importable module-level
    # function. Never import a path supplied in task configuration.
    if not inspect.isfunction(value) or value.__qualname__ != value.__name__:
        return None
    if value.__name__ == "<lambda>":
        return None
    try:
        pickle.dumps(value)
    except Exception:
        return None
    return value


def _same_direct_spec_references(left, right) -> bool:
    """Recognize an exact shallow copy without introspecting shared callables.

    All keys and values must match by identity (or exact immutable scalar
    equality). Other copies still need the full conservative fingerprint.
    Never invoke user-defined equality on templates or config objects.
    """
    if type(left) is not dict or type(right) is not dict:
        return False
    if any(type(key) is not str for key in left) or any(type(key) is not str for key in right):
        return False
    if left.keys() != right.keys():
        return False
    for key, value in left.items():
        other = right[key]
        if value is other:
            continue
        if type(value) is type(other) and type(value) in (str, bool, int, type(None)):
            if value == other:
                continue
        return False
    return True


def legacy_rule_worker_kwargs(task, *, task_pool, renderer_pool) -> dict:
    """Resolve a direct named task from the actual legacy renderer registry.

    A context-local shadow must match the renderer's complete task semantics.
    Do not use a display name, mapping alias, or fallback lookup when a
    context explicitly supplies a different task registry.
    """
    if (not isinstance(task, str) or "to json" not in task.lower()
            or not isinstance(renderer_pool, Mapping)):
        return {}
    try:
        spec = renderer_pool.get(task)
        if not isinstance(spec, Mapping) or not callable(spec.get("template")):
            return {}
        policy = parse_json_repair_policy(spec)
        if not (policy.generic or policy.multidim_evidence_quotes):
            return {}
        if policy.multidim_evidence_quotes and (
            not any(spec.get("template") is known for known in TRUSTED_MULTIDIM_SOURCE_RENDERERS)
            or spec.get("json_rule_slice_contract") != "multidim_event_slice_v1"
        ):
            return {}
        if task_pool is not None:
            if not isinstance(task_pool, Mapping):
                return {}
            context_spec = task_pool.get(task)
            if context_spec is not spec:
                if not isinstance(context_spec, Mapping):
                    return {}
                if (not _same_direct_spec_references(context_spec, spec)
                        and fingerprint_task(context_spec) != fingerprint_task(spec)):
                    return {}
        validator = _resolve_validator(spec.get("json_rule_slice_contract"))
        if validator is None:
            return {}
        return {"json_rule_policy": policy, "json_rule_slice_validator": validator}
    except Exception:
        # Invalid configuration must not change the legacy processing result.
        return {}
