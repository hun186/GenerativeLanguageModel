"""One-pass execution facade for the explicitly enabled Reduction Engine."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from czjLLM.reduction.config import ReductionConfig, ReductionConfigError
from czjLLM.reduction.contracts import ReducerResult
from czjLLM.reduction.reducers import LegacyJsonDeepMergeReducer
from czjLLM.reduction.registry import ReducerRegistry, get_default_registry


_COMBINE_DEEP_MERGE_DEFAULTS = {
    "conflict_policy": "prefer_left",
    "dedup_lists": True,
    "audit_enabled": True,
    "max_audit_samples": 10,
}


def reduce_single_pass(
    items: Iterable[Any],
    config: ReductionConfig,
    *,
    registry: Optional[ReducerRegistry] = None,
    context: Optional[Mapping[str, Any]] = None,
) -> ReducerResult:
    """Resolve and execute exactly one configured reducer call."""

    if not isinstance(config, ReductionConfig):
        raise TypeError("config must be a validated ReductionConfig")
    if not config.enabled:
        raise ReductionConfigError("single-pass reduction requires enabled=true")
    if config.controller != "single_pass" or not config.profile:
        raise ReductionConfigError("invalid single-pass reduction configuration")

    selected_registry = registry or get_default_registry()
    registered = selected_registry.get(config.profile)
    if registered is None:
        raise ReductionConfigError(f"Unknown reduction profile: {config.profile!r}")

    if config.profile == "legacy_json_deep_merge":
        options = dict(_COMBINE_DEEP_MERGE_DEFAULTS)
        options.update(config.options)
        reducer = LegacyJsonDeepMergeReducer(**options)
    else:
        reducer = registered

    return reducer.reduce(items, context=context)
