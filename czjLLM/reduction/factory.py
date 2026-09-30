"""Central construction of fresh, configured built-in reducers."""

from __future__ import annotations

from typing import Any, Mapping

from .config import ReductionConfigError
from .reducers import (
    CompositeReducer, DedupReducer, EntityUnionReducer, GroupReducer,
    LegacyJsonDeepMergeReducer, RankReducer, TopKReducer,
)
from .registry import ReducerRegistry

_DEEP_MERGE_DEFAULTS = {"conflict_policy": "prefer_left", "dedup_lists": True,
                        "audit_enabled": True, "max_audit_samples": 10}


def build_configured_reducer(profile: str, options: Mapping[str, Any], registry: ReducerRegistry, *, nested: bool = False):
    if nested and profile == "composite":
        raise ReductionConfigError("nested composite reducers are not supported")
    if profile == "legacy_json_deep_merge":
        values = {**_DEEP_MERGE_DEFAULTS, **dict(options)}
        return LegacyJsonDeepMergeReducer(**values)
    builders = {
        "dedup": lambda: DedupReducer(tuple(options.get("key_paths", ()))),
        "group": lambda: GroupReducer(tuple(options["by"])),
        "entity_union": lambda: EntityUnionReducer(tuple(options.get("key_paths", ()))),
        "rank": lambda: RankReducer(options["score_path"], options.get("descending", True)),
        "top_k": lambda: TopKReducer(options["k"]),
        "composite": lambda: CompositeReducer(tuple(
            build_configured_reducer(step["profile"], step["options"], registry, nested=True)
            for step in options["steps"]
        )),
    }
    if profile in builders:
        return builders[profile]()
    reducer = registry.get(profile)
    if reducer is None:
        raise ReductionConfigError(f"Unknown reduction profile: {profile!r}")
    return reducer
