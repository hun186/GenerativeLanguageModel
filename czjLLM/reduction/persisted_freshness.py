"""Bind persisted-result freshness to the effective production executable once."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .execution import (
    ExecutionContext, Executable, ExecutableResult, TaskExecutable,
    _stable_semantics, executable_semantic_fingerprint,
)
from .executable_pipeline import StagePipelineExecutable
from .runtime_task import ProductionTaskRuntime
from .config import ReductionConfig, parse_reduction_config


@dataclass(frozen=True)
class PersistedProcessingExecutable:
    """Fingerprint-only wrapper for production row processing plus combine semantics."""

    processing: Executable
    reduction: Any = None
    executor_type: str = field(default="persisted_processing", init=False)
    contract_version: str = field(default="reduction-persisted-processing-v1", init=False)

    def execute(self, item: Any, context: ExecutionContext) -> ExecutableResult:
        return self.processing.execute(item, context)

    def fingerprint_metadata(self, context: ExecutionContext) -> Mapping[str, Any]:
        return {
            "executor_type": self.executor_type,
            "contract_version": self.contract_version,
            "processing": self.processing.fingerprint_metadata(context),
            "reduction": _stable_semantics(self.reduction),
        }


def effective_persisted_executable(ctx: Any) -> Executable:
    """Use an explicit K1/K2 executable, an ordinary stage pipeline, or one task."""
    explicit = getattr(ctx, "semantic_freshness_executable", None)
    if explicit is not None:
        if not callable(getattr(explicit, "fingerprint_metadata", None)):
            raise TypeError("semantic_freshness_executable must implement Executable")
        return explicit
    stages = getattr(ctx, "stages", None)
    processing: Executable = (
        StagePipelineExecutable(stages)
        if isinstance(stages, (list, tuple)) and stages
        else TaskExecutable(getattr(ctx, "task", ""))
    )
    raw_reduction = getattr(ctx, "reduction", None)
    reduction = raw_reduction if isinstance(raw_reduction, ReductionConfig) else parse_reduction_config(raw_reduction)
    return PersistedProcessingExecutable(processing, {
        "enabled": reduction.enabled,
        "profile": reduction.profile,
        "controller": reduction.controller,
        "options": reduction.options,
        "controller_options": reduction.controller_options,
        "runtime": reduction.runtime,
    })


def bind_persisted_execution_fingerprint(ctx: Any, adapter: Any) -> str | None:
    """Resolve ``auto`` exactly once and bind context, adapter freshness and sink input."""
    cfg = getattr(adapter, "cfg", None) or {}
    if getattr(ctx, "mode", "").lower() == "es":
        namespace = cfg.get("rerun") or {}
    else:
        namespace = cfg.get("semantic_freshness") or {}
    configured = namespace.get("execution_fingerprint")
    if not configured:
        return None
    if str(configured).strip().lower() == "auto":
        runtime = ProductionTaskRuntime(ctx)
        context = ExecutionContext(
            runtime_ctx=ctx,
            task_runtime=runtime,
            executable_registry=getattr(ctx, "executable_registry", None),
        )
        expected = executable_semantic_fingerprint(effective_persisted_executable(ctx), context)
    else:
        expected = str(configured)
    ctx.expected_execution_fingerprint = expected
    if getattr(ctx, "mode", "").lower() == "es":
        cfg.setdefault("rerun", {})["execution_fingerprint"] = expected
    else:
        cfg.setdefault("semantic_freshness", {})["execution_fingerprint"] = expected
    return expected
