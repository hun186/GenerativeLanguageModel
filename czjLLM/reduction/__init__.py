"""Reduction Engine contracts, strict config, and one-pass routing."""

from .config import ReductionConfig, ReductionConfigError, parse_reduction_config
from .contracts import Reducer, ReducerResult
from .engine import reduce_single_pass
from .controllers import AdaptiveHierarchicalController, FixedRoundsController
from .hierarchical import reduce_hierarchical_text
from .registry import (
    ReducerRegistry,
    get_default_registry,
    register_builtin_reducers,
    register_reducer,
)

__all__ = [
    "Reducer",
    "ReductionConfig",
    "ReductionConfigError",
    "ReducerRegistry",
    "ReducerResult",
    "AdaptiveHierarchicalController",
    "FixedRoundsController",
    "get_default_registry",
    "parse_reduction_config",
    "reduce_single_pass",
    "reduce_hierarchical_text",
    "register_builtin_reducers",
    "register_reducer",
]
