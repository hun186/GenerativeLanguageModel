"""Exact, source-independent deterministic reducers."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

from czjLLM.reduction.contracts import Reducer, ReducerResult


class DeterministicReducerError(ValueError):
    """Raised when deterministic reducer input violates its strict contract."""


def normalize_json_value(value: Any, path: str = "value") -> Any:
    """Validate and detach a value into JSON-native dictionaries and lists."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise DeterministicReducerError(f"{path} must not contain NaN/Infinity")
        return value
    if isinstance(value, Mapping):
        normalized = {}
        for key, member in value.items():
            if not isinstance(key, str):
                raise DeterministicReducerError(f"{path} mapping keys must be strings")
            normalized[key] = normalize_json_value(member, f"{path}.{key}")
        return normalized
    if isinstance(value, (list, tuple)):
        return [
            normalize_json_value(member, f"{path}[{index}]")
            for index, member in enumerate(value)
        ]
    raise DeterministicReducerError(
        f"{path} must contain only JSON-compatible values, not {type(value).__name__}"
    )


def validate_json_value(value: Any, path: str = "value") -> Any:
    """Validate a deterministic JSON value without mutating the caller's value."""

    normalize_json_value(value, path)
    return value


def canonical_json(value: Any) -> str:
    normalized = normalize_json_value(value)
    return json.dumps(
        normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def validate_path(path: Any, label: str = "path") -> str:
    if (
        not isinstance(path, str)
        or not path
        or any(not part or not part.strip() for part in path.split("."))
    ):
        raise DeterministicReducerError(f"{label} must be a non-empty dotted mapping path")
    return path


def _validate_paths(paths: Any, label: str, *, required: bool = False) -> tuple[str, ...]:
    if isinstance(paths, (str, bytes)) or not isinstance(paths, (list, tuple)):
        raise DeterministicReducerError(f"{label} must be a sequence of dotted mapping paths")
    normalized = tuple(validate_path(path, label) for path in paths)
    if required and not normalized:
        raise DeterministicReducerError(f"{label} must contain at least one path")
    return normalized


def get_path(value: Any, path: str) -> Any:
    validate_path(path)
    current = value
    for part in path.split("."):
        if not isinstance(current, Mapping):
            raise DeterministicReducerError(
                f"Cannot resolve path {path!r}: {part!r} parent is not a mapping"
            )
        if part not in current:
            raise DeterministicReducerError(f"Missing required path {path!r}")
        current = current[part]
    validate_json_value(current, path)
    return current


def _key(item: Any, paths: Sequence[str]) -> str:
    return canonical_json([get_path(item, path) for path in paths] if paths else item)


@dataclass(frozen=True)
class DedupReducer:
    key_paths: tuple[str, ...] = ()
    profile: str = "dedup"
    contract_version: str = "1"
    requires_stable_order: bool = True
    preserves_order: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "key_paths", _validate_paths(self.key_paths, "key_paths"))

    def reduce(self, items: Iterable[Any], context: Optional[Mapping[str, Any]] = None) -> ReducerResult:
        del context
        prepared, output, seen = list(items), [], set()
        for item in prepared:
            fingerprint = _key(item, self.key_paths)
            if fingerprint not in seen:
                seen.add(fingerprint); output.append(item)
        duplicates = len(prepared) - len(output)
        return ReducerResult(output, self.profile, self.contract_version, duplicates > 0,
                             metrics={"input_count": len(prepared), "output_count": len(output), "duplicate_count": duplicates})


@dataclass(frozen=True)
class GroupReducer:
    by: tuple[str, ...] = ()
    profile: str = "group"
    contract_version: str = "1"
    requires_stable_order: bool = True
    preserves_order: bool = True
    _allow_unconfigured: bool = field(default=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "by",
            _validate_paths(self.by, "by", required=not self._allow_unconfigured),
        )

    @classmethod
    def _registry_prototype(cls) -> "GroupReducer":
        return cls(_allow_unconfigured=True)

    def reduce(self, items: Iterable[Any], context: Optional[Mapping[str, Any]] = None) -> ReducerResult:
        del context
        if not self.by:
            raise DeterministicReducerError("group requires at least one by path")
        prepared, groups, indexes = list(items), [], {}
        for item in prepared:
            values = [get_path(item, path) for path in self.by]
            fingerprint = canonical_json(values)
            if fingerprint not in indexes:
                indexes[fingerprint] = len(groups)
                groups.append({"key": [{"path": path, "value": value} for path, value in zip(self.by, values)], "items": []})
            groups[indexes[fingerprint]]["items"].append(item)
        return ReducerResult(groups, self.profile, self.contract_version, bool(prepared),
                             metrics={"input_count": len(prepared), "group_count": len(groups)})


@dataclass(frozen=True)
class EntityUnionReducer:
    key_paths: tuple[str, ...] = ()
    profile: str = "entity_union"
    contract_version: str = "1"
    requires_stable_order: bool = True
    preserves_order: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "key_paths", _validate_paths(self.key_paths, "key_paths"))

    def reduce(self, items: Iterable[Any], context: Optional[Mapping[str, Any]] = None) -> ReducerResult:
        del context
        prepared, entities = list(items), []
        for index, item in enumerate(prepared):
            members = item if isinstance(item, (list, tuple)) else (item,)
            for member in members:
                if not isinstance(member, Mapping):
                    raise DeterministicReducerError(f"entity member at input {index} must be a mapping")
                validate_json_value(member); entities.append(member)
        result = DedupReducer(self.key_paths).reduce(entities)
        return ReducerResult(result.payload, self.profile, self.contract_version,
                             result.changed or len(prepared) != len(entities), metrics={"input_count": len(prepared), "entity_input_count": len(entities), "output_count": len(result.payload), "duplicate_count": result.metrics["duplicate_count"]})


@dataclass(frozen=True)
class RankReducer:
    score_path: str = ""
    descending: bool = True
    profile: str = "rank"
    contract_version: str = "1"
    requires_stable_order: bool = True
    preserves_order: bool = False
    _allow_unconfigured: bool = field(default=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self._allow_unconfigured:
            validate_path(self.score_path, "score_path")
        if type(self.descending) is not bool:
            raise DeterministicReducerError("descending must be a boolean")

    @classmethod
    def _registry_prototype(cls) -> "RankReducer":
        return cls(_allow_unconfigured=True)

    def reduce(self, items: Iterable[Any], context: Optional[Mapping[str, Any]] = None) -> ReducerResult:
        del context
        validate_path(self.score_path, "score_path")
        prepared = list(items)
        scored = []
        for item in prepared:
            if not isinstance(item, Mapping):
                raise DeterministicReducerError("rank items must be mappings")
            score = get_path(item, self.score_path)
            if isinstance(score, bool) or not isinstance(score, (int, float)) or (isinstance(score, float) and not math.isfinite(score)):
                raise DeterministicReducerError("rank scores must be finite integers or floats (not booleans)")
            scored.append((score, item))
        output = [item for _, item in sorted(scored, key=lambda pair: pair[0], reverse=self.descending)]
        return ReducerResult(output, self.profile, self.contract_version, output != prepared,
                             metrics={"input_count": len(prepared), "output_count": len(output)})


@dataclass(frozen=True)
class TopKReducer:
    k: int = 1
    profile: str = "top_k"
    contract_version: str = "1"
    requires_stable_order: bool = True
    preserves_order: bool = True

    def __post_init__(self) -> None:
        if type(self.k) is not int or self.k <= 0:
            raise DeterministicReducerError("top_k k must be a positive integer")

    def reduce(self, items: Iterable[Any], context: Optional[Mapping[str, Any]] = None) -> ReducerResult:
        del context
        prepared = list(items); output = prepared[:self.k]
        return ReducerResult(output, self.profile, self.contract_version, len(output) != len(prepared),
                             metrics={"input_count": len(prepared), "output_count": len(output), "dropped_count": len(prepared) - len(output), "k": self.k})


class CompositeReducer:
    profile = "composite"
    contract_version = "1"

    def __init__(self, steps: Sequence[Reducer] = ()) -> None:
        if isinstance(steps, (str, bytes)) or not isinstance(steps, (list, tuple)):
            raise DeterministicReducerError("composite steps must be a sequence of reducers")
        self.steps = tuple(steps)
        if any(getattr(step, "profile", None) == self.profile for step in self.steps):
            raise DeterministicReducerError("nested composite reducers are not supported")
        if any(not isinstance(getattr(step, "profile", None), str) for step in self.steps):
            raise DeterministicReducerError("composite steps must be reducers with profiles")
        self.requires_stable_order = any(step.requires_stable_order for step in self.steps)
        self.preserves_order = all(step.preserves_order for step in self.steps)

    def reduce(self, items: Iterable[Any], context: Optional[Mapping[str, Any]] = None) -> ReducerResult:
        if not self.steps:
            raise DeterministicReducerError("composite requires at least one configured step")
        current = list(items); input_count = len(current); warnings = []; audit = []; changed = False; payload: Any = current
        for index, step in enumerate(self.steps):
            result = step.reduce(current, context=context)
            payload = result.payload; changed = changed or result.changed; warnings.extend(result.warnings)
            audit.append({"index": index, "profile": result.profile, "contract_version": result.contract_version, "changed": result.changed, "metrics": dict(result.metrics), "warning_count": len(result.warnings)})
            current = list(payload) if isinstance(payload, (list, tuple)) else [payload]
        metrics = {"step_count": len(self.steps), "input_count": input_count}
        if isinstance(payload, (list, tuple)):
            metrics["output_count"] = len(payload)
        return ReducerResult(payload, self.profile, self.contract_version, changed, tuple(warnings),
                             audit={"steps": tuple(audit)}, metrics=metrics)
