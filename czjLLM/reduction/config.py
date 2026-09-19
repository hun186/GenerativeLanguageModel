"""Strict PR C configuration boundary for opt-in reduction."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Optional

from czjLLM.reduction.registry import ReducerRegistry, get_default_registry


class ReductionConfigError(ValueError):
    """Raised when an explicit reduction configuration is invalid."""


_TOP_LEVEL_KEYS = frozenset({"enabled", "profile", "controller", "options"})
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
    if not isinstance(controller, str) or controller != "single_pass":
        raise ReductionConfigError(
            "reduction.controller must be 'single_pass' in PR C"
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
    if enabled and merge_slices:
        raise ReductionConfigError(
            "reduction.enabled=true is mutually exclusive with merge_slices=true"
        )

    return ReductionConfig(
        enabled=enabled,
        profile=profile,
        controller=controller,
        options=options,
    )
