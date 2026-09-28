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


class ReductionConfigError(ValueError):
    """Raised when an explicit reduction configuration is invalid."""


_TOP_LEVEL_KEYS = frozenset(
    {"enabled", "profile", "controller", "options", "controller_options", "runtime"}
)
_SUPPORTED_CONTROLLERS = frozenset(
    {"single_pass", "fixed_rounds", "adaptive_hierarchical"}
)
_SUPPORTED_PROFILES = frozenset(
    {"concat_text", "concat_json_list", "legacy_json_deep_merge"}
)
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
    allowed = _DEEP_MERGE_OPTION_KEYS if profile == "legacy_json_deep_merge" else frozenset()
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
