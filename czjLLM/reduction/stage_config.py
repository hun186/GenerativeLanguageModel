"""Strict, separate configuration parser for K1 ReductionStage."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from czjLLM.reduction.config import (
    ReductionConfig, ReductionConfigError, _SUPPORTED_CONTROLLERS, _SUPPORTED_PROFILES,
    _unexpected_keys, _validate_controller_options, _validate_options,
)
from czjLLM.reduction.execution import TaskExecutable
from czjLLM.reduction.executable_pipeline import PipelineRefExecutable
from czjLLM.reduction.registry import get_default_registry
from czjLLM.reduction.stage import TokenizerRoundPreparer


@dataclass(frozen=True)
class ReductionStageConfig:
    worker: TaskExecutable | PipelineRefExecutable
    worker_parallelism: int
    reduction: ReductionConfig
    round_preparer: TokenizerRoundPreparer | None


def _strict_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ReductionConfigError(f"{label} must be non-blank without surrounding whitespace")
    return value


def parse_reduction_stage_config(raw: Any) -> ReductionStageConfig:
    if not isinstance(raw, Mapping):
        raise ReductionConfigError("reduction_stage must be a mapping")
    _unexpected_keys(raw, frozenset({"worker", "worker_parallelism", "reduction", "round_preparer"}),
                     "reduction_stage")
    worker_raw = raw.get("worker")
    if not isinstance(worker_raw, Mapping):
        raise ReductionConfigError("reduction_stage.worker must be a mapping")
    kind = worker_raw.get("type")
    if kind == "task":
        _unexpected_keys(worker_raw, frozenset({"type", "task"}), "reduction_stage.worker")
        worker = TaskExecutable(_strict_text(worker_raw.get("task"), "worker.task"))
    elif kind == "pipeline_ref":
        _unexpected_keys(worker_raw, frozenset({"type", "ref"}), "reduction_stage.worker")
        worker = PipelineRefExecutable(_strict_text(worker_raw.get("ref"), "worker.ref"))
    else:
        raise ReductionConfigError("worker.type must be task or pipeline_ref")
    parallelism = raw.get("worker_parallelism", 1)
    if type(parallelism) is not int or parallelism <= 0:
        raise ReductionConfigError("worker_parallelism must be a positive integer")
    reduction_raw = raw.get("reduction")
    if not isinstance(reduction_raw, Mapping):
        raise ReductionConfigError("reduction_stage.reduction must be a mapping")
    _unexpected_keys(reduction_raw, frozenset({"enabled", "profile", "controller", "options", "controller_options"}),
                     "reduction_stage.reduction")
    enabled = reduction_raw.get("enabled", False)
    if enabled is not True:
        raise ReductionConfigError("reduction_stage.reduction.enabled must be true")
    controller = reduction_raw.get("controller", "single_pass")
    if controller not in _SUPPORTED_CONTROLLERS:
        raise ReductionConfigError("invalid reduction_stage reduction controller")
    profile_raw = reduction_raw.get("profile")
    if not isinstance(profile_raw, str) or not profile_raw.strip():
        raise ReductionConfigError("reduction.profile is required")
    profile = get_default_registry().normalize_name(profile_raw)
    if profile not in _SUPPORTED_PROFILES or not get_default_registry().has(profile):
        raise ReductionConfigError(f"Unknown reduction profile: {profile_raw!r}")
    options = _validate_options(profile, reduction_raw.get("options", {}))
    controller_options = _validate_controller_options(controller, reduction_raw.get("controller_options", {}))
    if controller != "single_pass" and profile != "concat_text":
        raise ReductionConfigError("hierarchical reduction controllers support profile concat_text only")
    reduction = ReductionConfig(True, profile, controller, options, controller_options,
                                MappingProxyType({}))
    preparer_raw = raw.get("round_preparer")
    if controller == "single_pass":
        if preparer_raw is not None:
            raise ReductionConfigError("round_preparer must be absent for single_pass")
        preparer = None
    else:
        if not isinstance(preparer_raw, Mapping):
            raise ReductionConfigError("round_preparer is required for hierarchical reduction")
        _unexpected_keys(preparer_raw, frozenset({"type", "task"}), "round_preparer")
        if preparer_raw.get("type") != "tokenizer":
            raise ReductionConfigError("round_preparer.type must be tokenizer")
        preparer = TokenizerRoundPreparer(_strict_text(preparer_raw.get("task"), "round_preparer.task"))
    return ReductionStageConfig(worker, parallelism, reduction, preparer)
