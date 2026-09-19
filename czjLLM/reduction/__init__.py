"""Inactive Reduction Engine reducer contracts and built-in registry."""

from .contracts import Reducer, ReducerResult
from .registry import (
    ReducerRegistry,
    get_default_registry,
    register_builtin_reducers,
    register_reducer,
)

__all__ = [
    "Reducer",
    "ReducerRegistry",
    "ReducerResult",
    "get_default_registry",
    "register_builtin_reducers",
    "register_reducer",
]
