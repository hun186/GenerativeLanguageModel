"""One-pass execution facade for the explicitly enabled Reduction Engine."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from czjLLM.reduction.config import ReductionConfig, ReductionConfigError
from czjLLM.reduction.contracts import ReducerResult
from czjLLM.reduction.factory import build_configured_reducer
from czjLLM.reduction.registry import ReducerRegistry, get_default_registry


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
    reducer = build_configured_reducer(config.profile, config.options, selected_registry)

    return reducer.reduce(items, context=context)
