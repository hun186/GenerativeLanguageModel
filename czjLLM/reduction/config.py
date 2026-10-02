"""Strict production configuration boundary for opt-in reduction."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Optional

from czjLLM.reduction.controllers import (
    AdaptiveHierarchicalController,
    FixedRoundsController,
    ReductionController,
)
from czjLLM.reduction.registry import ReducerRegistry, get_default_registry
from czjLLM.reduction.reducers.deterministic import (
    DeterministicReducerError,
    validate_path,
)
from czjLLM.reduction.reducers.structured_relational import (
    StructuredRelationalError, validate_structured_relational_options,
)


class ReductionConfigError(ValueError):
    """Raised when an explicit reduction configuration is invalid."""


_TOP_LEVEL_KEYS = frozenset(
    {"enabled", "profile", "controller", "options", "controller_options", "runtime"}
)
_SUPPORTED_CONTROLLERS = frozenset(
    {"single_pass", "fixed_rounds", "adaptive_hierarchical"}
)
_SUPPORTED_PROFILES = frozenset(
    {"concat_text", "concat_json_list", "legacy_json_deep_merge", "dedup",
     "group", "entity_union", "rank", "top_k", "composite", "semantic_llm",
     "structured_relational"}
)
_COMPOSITE_STEP_PROFILES = _SUPPORTED_PROFILES - {"composite"}
_DEEP_MERGE_OPTION_KEYS = frozenset(
    {"conflict_policy", "dedup_lists", "audit_enabled", "max_audit_samples"}
)
_CONFLICT_POLICIES = frozenset(
    {"prefer_left", "prefer_right", "longer_str", "non_empty"}
)


@dataclass(frozen=True)
class ReductionConfig:
    """Normalized immutable reduction settings used by production routing."""

    enabled: bool = False
    profile: Optional[str] = None
    controller: str = "single_pass"
    options: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    controller_options: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    runtime: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def build_controller(self) -> ReductionController:
        """Build the already-validated D1 controller for hierarchical routing."""
        if self.controller == "fixed_rounds":
            return FixedRoundsController(**dict(self.controller_options))
        if self.controller == "adaptive_hierarchical":
            return AdaptiveHierarchicalController(**dict(self.controller_options))
        raise ReductionConfigError("single_pass does not use a hierarchical controller")

    def contains_semantic_llm(self) -> bool:
        if self.profile == "semantic_llm":
            return True
        return self.profile == "composite" and any(
            step["profile"] == "semantic_llm" for step in self.options.get("steps", ())
        )

    def requires_semantic_runtime(self) -> bool:
        """Whether execution depends on the PR I semantic LLM runtime."""
        return self.contains_semantic_llm()


def _unexpected_keys(raw: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    unexpected = sorted(set(raw) - allowed)
    if unexpected:
        raise ReductionConfigError(
            f"Unsupported {label} key(s): {', '.join(map(str, unexpected))}"
        )


def _validate_options(profile: Optional[str], raw: Any) -> Mapping[str, Any]:
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise ReductionConfigError("reduction.options must be a mapping")

    options = dict(raw)
    allowed_by_profile = {
        "legacy_json_deep_merge": _DEEP_MERGE_OPTION_KEYS,
        "dedup": frozenset({"key_paths"}), "group": frozenset({"by"}),
        "entity_union": frozenset({"key_paths"}),
        "rank": frozenset({"score_path", "descending"}),
        "top_k": frozenset({"k"}), "composite": frozenset({"steps"}),
        "semantic_llm": frozenset({"task"}),
        "structured_relational": frozenset({"entity_sets", "references"}),
    }
    allowed = allowed_by_profile.get(profile, frozenset())
    _unexpected_keys(options, allowed, "reduction option")

    if "conflict_policy" in options:
        policy = options["conflict_policy"]
        if not isinstance(policy, str) or policy not in _CONFLICT_POLICIES:
            raise ReductionConfigError(
                "reduction.options.conflict_policy must be one of: "
                + ", ".join(sorted(_CONFLICT_POLICIES))
            )
    for key in ("dedup_lists", "audit_enabled"):
        if key in options and type(options[key]) is not bool:
            raise ReductionConfigError(f"reduction.options.{key} must be a boolean")
    if "max_audit_samples" in options:
        value = options["max_audit_samples"]
        if type(value) is not int or value < 0:
            raise ReductionConfigError(
                "reduction.options.max_audit_samples must be a non-negative integer"
            )
    def paths(name: str, required: bool = False) -> tuple[str, ...]:
        value = options.get(name)
        if value is None and not required:
            return ()
        if not isinstance(value, (list, tuple)) or not value:
            raise ReductionConfigError(f"reduction.options.{name} must be a non-empty sequence")
        result = []
        for path in value:
            try:
                validate_path(path, f"reduction.options.{name}")
            except DeterministicReducerError:
                raise ReductionConfigError(f"reduction.options.{name} contains an invalid path")
            result.append(path)
        return tuple(result)

    if profile in {"dedup", "entity_union"} and "key_paths" in options:
        options["key_paths"] = paths("key_paths")
    if profile == "group":
        options["by"] = paths("by", required=True)
    if profile == "rank":
        score_path = options.get("score_path")
        try:
            validate_path(score_path, "reduction.options.score_path")
        except DeterministicReducerError:
            raise ReductionConfigError("reduction.options.score_path is required and must be a valid path")
        if "descending" in options and type(options["descending"]) is not bool:
            raise ReductionConfigError("reduction.options.descending must be a boolean")
    if profile == "top_k":
        if type(options.get("k")) is not int or options["k"] <= 0:
            raise ReductionConfigError("reduction.options.k must be a positive integer")
    if profile == "semantic_llm":
        task = options.get("task")
        if not isinstance(task, str) or not task.strip():
            raise ReductionConfigError("reduction.options.task is required and must be a non-blank string")
    if profile == "structured_relational":
        try:
            entities, references = validate_structured_relational_options(options)
        except StructuredRelationalError as exc:
            raise ReductionConfigError(f"Invalid structured_relational options: {exc}") from exc
        options["entity_sets"] = tuple(MappingProxyType({
            "name": item.name, "collection_path": item.collection_path,
            "id_field": item.id_field, "canonical_prefix": item.canonical_prefix,
        }) for item in entities)
        options["references"] = tuple(MappingProxyType({
            "collection_path": item.collection_path, "field": item.field, "target": item.target,
        }) for item in references)
    if profile == "composite":
        steps = options.get("steps")
        if not isinstance(steps, (list, tuple)) or not steps:
            raise ReductionConfigError("reduction.options.steps must be a non-empty sequence")
        normalized = []
        registry = get_default_registry()
        for index, step in enumerate(steps):
            if not isinstance(step, Mapping):
                raise ReductionConfigError(f"composite step {index} must be a mapping")
            _unexpected_keys(step, frozenset({"profile", "options"}), f"composite step {index}")
            if "profile" not in step:
                raise ReductionConfigError(f"composite step {index} requires profile")
            name = step["profile"]
            if not isinstance(name, str) or not name.strip():
                raise ReductionConfigError(f"composite step {index} profile must be a non-empty string")
            canonical = registry.normalize_name(name)
            if canonical == "composite":
                raise ReductionConfigError("nested composite reducers are not supported")
            if canonical == "structured_relational":
                raise ReductionConfigError("structured_relational is not supported inside composite")
            if canonical not in _COMPOSITE_STEP_PROFILES or not registry.has(canonical):
                raise ReductionConfigError(f"Unknown composite step profile: {name!r}")
            step_options = _validate_options(canonical, step.get("options", {}))
            normalized.append(MappingProxyType({"profile": canonical, "options": step_options}))
        semantic_indexes = [i for i, step in enumerate(normalized) if step["profile"] == "semantic_llm"]
        if len(semantic_indexes) > 1:
            raise ReductionConfigError("semantic_llm may appear at most once in a composite")
        if semantic_indexes and semantic_indexes[0] != len(normalized) - 1:
            raise ReductionConfigError("semantic_llm must be the final composite step")
        options["steps"] = tuple(normalized)
    return MappingProxyType(options)


def _validate_controller_options(controller: str, raw: Any) -> Mapping[str, Any]:
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise ReductionConfigError("reduction.controller_options must be a mapping")
    values = dict(raw)
    if controller == "single_pass":
        if values:
            raise ReductionConfigError(
                "reduction.controller_options must be absent or empty for single_pass"
            )
        return MappingProxyType({})

    required = (
        {"rounds"}
        if controller == "fixed_rounds"
        else {"target_max_chars", "max_rounds", "min_reduction_ratio"}
    )
    _unexpected_keys(values, frozenset(required), "reduction controller option")
    missing = sorted(required - set(values))
    if missing:
        raise ReductionConfigError(
            "Missing reduction.controller_options key(s): " + ", ".join(missing)
        )
    try:
        if controller == "fixed_rounds":
            FixedRoundsController(**values)
        else:
            AdaptiveHierarchicalController(**values)
    except (TypeError, ValueError) as exc:
        raise ReductionConfigError(f"Invalid reduction.controller_options: {exc}") from exc
    return MappingProxyType(values)


def _validate_runtime(controller: str, raw: Any) -> Mapping[str, Any]:
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise ReductionConfigError("reduction.runtime must be a mapping")
    values = dict(raw)
    _unexpected_keys(values, frozenset({"round_task"}), "reduction runtime")
    if controller == "single_pass":
        if values:
            raise ReductionConfigError(
                "reduction.runtime must be absent or empty for single_pass"
            )
        return MappingProxyType({})
    task = values.get("round_task")
    if not isinstance(task, str) or not task.strip():
        raise ReductionConfigError(
            "reduction.runtime.round_task is required and must be a non-empty string"
        )
    return MappingProxyType({"round_task": task.strip()})


def parse_reduction_config(
    raw: Any,
    *,
    merge_slices: bool = False,
    registry: Optional[ReducerRegistry] = None,
) -> ReductionConfig:
    """Normalize and strictly validate the complete PR C reduction mapping.

    Absence and mappings without explicit ``enabled: true`` are inactive.  A
    supplied value must nevertheless be a valid mapping so partially migrated
    configuration cannot be silently misinterpreted.
    """

    if raw is None:
        return ReductionConfig()
    if not isinstance(raw, Mapping):
        raise ReductionConfigError("reduction must be a mapping")

    _unexpected_keys(raw, _TOP_LEVEL_KEYS, "reduction")
    enabled = raw.get("enabled", False)
    if type(enabled) is not bool:
        raise ReductionConfigError("reduction.enabled must be a boolean")

    controller = raw.get("controller", "single_pass")
    if not isinstance(controller, str) or controller not in _SUPPORTED_CONTROLLERS:
        raise ReductionConfigError(
            "reduction.controller must be one of: "
            + ", ".join(sorted(_SUPPORTED_CONTROLLERS))
        )

    profile_value = raw.get("profile")
    profile: Optional[str] = None
    if profile_value is not None:
        if not isinstance(profile_value, str) or not profile_value.strip():
            raise ReductionConfigError("reduction.profile must be a non-empty string")
        selected_registry = registry or get_default_registry()
        profile = selected_registry.normalize_name(profile_value)
        if profile not in _SUPPORTED_PROFILES or not selected_registry.has(profile):
            raise ReductionConfigError(f"Unknown reduction profile: {profile_value!r}")
    elif enabled:
        raise ReductionConfigError(
            "reduction.profile is required when reduction.enabled is true"
        )

    options = _validate_options(profile, raw.get("options", {}))
    controller_options = _validate_controller_options(
        controller, raw.get("controller_options", {})
    )
    runtime = _validate_runtime(controller, raw.get("runtime", {}))
    if controller != "single_pass" and profile != "concat_text":
        raise ReductionConfigError(
            "hierarchical reduction controllers support profile concat_text only"
        )
    if enabled and merge_slices:
        raise ReductionConfigError(
            "reduction.enabled=true is mutually exclusive with merge_slices=true"
        )

    return ReductionConfig(
        enabled=enabled,
        profile=profile,
        controller=controller,
        options=options,
        controller_options=controller_options,
        runtime=runtime,
    )
