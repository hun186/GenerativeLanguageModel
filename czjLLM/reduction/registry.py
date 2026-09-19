"""Independent registry for source-agnostic reducers."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Optional

from czjLLM.reduction.contracts import Reducer
from czjLLM.reduction.reducers import (
    ConcatJsonListReducer,
    ConcatTextReducer,
    LegacyJsonDeepMergeReducer,
)


class ReducerRegistry:
    """Map canonical profile names and aliases to reducer instances."""

    def __init__(self) -> None:
        self._reducers: Dict[str, Reducer] = {}
        self._aliases: Dict[str, str] = {}

    @staticmethod
    def canonicalize(value: Any) -> str:
        return re.sub(r"_+", "_", re.sub(r"[-\s]+", "_", str(value).strip().lower()))

    def register(
        self,
        name: str,
        reducer: Reducer,
        *,
        aliases: Optional[Iterable[str]] = None,
    ) -> None:
        canonical_name = self.canonicalize(name)
        if not canonical_name:
            raise ValueError("Reducer profile name must not be empty")
        self._reducers[canonical_name] = reducer
        self._aliases[canonical_name] = canonical_name
        for alias in aliases or ():
            canonical_alias = self.canonicalize(alias)
            if not canonical_alias:
                raise ValueError("Reducer alias must not be empty")
            self._aliases[canonical_alias] = canonical_name

    def normalize_name(self, value: Any) -> str:
        canonical_name = self.canonicalize(value)
        return self._aliases.get(canonical_name, canonical_name)

    def get(self, name: str) -> Optional[Reducer]:
        """Return the named reducer, or ``None`` without applying a fallback."""

        return self._reducers.get(self.normalize_name(name))

    def has(self, name: str) -> bool:
        return self.get(name) is not None


def register_builtin_reducers(registry: ReducerRegistry) -> None:
    registry.register("concat_text", ConcatTextReducer(), aliases=("text_concat",))
    registry.register(
        "concat_json_list",
        ConcatJsonListReducer(),
        aliases=("json_list_concat",),
    )
    registry.register(
        "legacy_json_deep_merge",
        LegacyJsonDeepMergeReducer(),
        aliases=("legacy_deep_merge",),
    )


_DEFAULT_REGISTRY = ReducerRegistry()
register_builtin_reducers(_DEFAULT_REGISTRY)


def get_default_registry() -> ReducerRegistry:
    return _DEFAULT_REGISTRY


def register_reducer(
    name: str,
    reducer: Reducer,
    *,
    aliases: Optional[Iterable[str]] = None,
) -> None:
    _DEFAULT_REGISTRY.register(name, reducer, aliases=aliases)
