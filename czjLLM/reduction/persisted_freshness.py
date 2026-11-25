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


def observed_computed_execution_fingerprint(ctx: Any) -> str | None:
    """Return a matching auto-computed binding, never a literal freshness override.

    Process-local observation only: not authenticated identity, source proof,
    a fresh rehash of mutable execution state, or permission to charge a retry.
    """
    computed = getattr(ctx, "_computed_persisted_execution_fingerprint", None)
    expected = getattr(ctx, "expected_execution_fingerprint", None)
    if (type(computed) is str and len(computed) == 64
            and all(c in "0123456789abcdef" for c in computed)
            and type(expected) is str and computed == expected):
        return computed
    return None


def reobserve_computed_es_execution_fingerprint(ctx: Any, adapter: Any) -> str | None:
    """Explicit current semantic rehash for a narrow ES observation.

    No new binding, provider call, observer initialization or dispatch.
    An exact match is not an immutable execution receipt or authentication.
    Explicit executables may supply arbitrary metadata and remain unsupported.
    """
    try:
        if getattr(ctx, "mode", "").lower() != "es":
            return None
        if getattr(ctx, "_es_adapter", None) is not adapter:
            return None
        if getattr(ctx, "semantic_freshness_executable", None) is not None:
            return None
        cfg = adapter.cfg
        rr = cfg.get("rerun") or {}
        bound = observed_computed_execution_fingerprint(ctx)
        if bound is None or rr.get("enable") is not True or rr.get("execution_fingerprint") != bound:
            return None
        spec = getattr(ctx, "model_spec", {}) or {}
        if getattr(ctx, "mock_llm_mode", False) or spec.get("mock_llm_mode", False):
            return None
        # Use the same semantic runtime as the binder, without constructing
        # operational cancellation/observer state.
        context = ExecutionContext(
            runtime_ctx=ctx, task_runtime=ProductionTaskRuntime(ctx),
            executable_registry=getattr(ctx, "executable_registry", None),
        )
        current = executable_semantic_fingerprint(effective_persisted_executable(ctx), context)
        if (current == bound
                and observed_computed_execution_fingerprint(ctx) == bound
                and adapter.cfg is cfg and cfg.get("rerun") is rr
                and rr.get("enable") is True and rr.get("execution_fingerprint") == bound
                and getattr(ctx, "_es_adapter", None) is adapter
                and getattr(ctx, "semantic_freshness_executable", None) is None
                and not getattr(ctx, "mock_llm_mode", False)
                and not (getattr(ctx, "model_spec", {}) or {}).get("mock_llm_mode", False)):
            return current
    except Exception:
        # No raw task/prompt/model errors escape this optional observation.
        return None
    return None


def bind_persisted_execution_fingerprint(ctx: Any, adapter: Any) -> str | None:
    """Resolve ``auto`` exactly once and bind context, adapter freshness and sink input."""
    # Clear a previous observation even if this bind is disabled or fails.
    # The legacy expected fingerprint and adapter behavior are unchanged.
    ctx._computed_persisted_execution_fingerprint = None
    cfg = getattr(adapter, "cfg", None) or {}
    if getattr(ctx, "mode", "").lower() == "es":
        namespace = cfg.get("rerun") or {}
    else:
        namespace = cfg.get("semantic_freshness") or {}
    configured = namespace.get("execution_fingerprint")
    if not configured:
        return None
    auto = str(configured).strip().lower() == "auto"
    if auto:
        from .production_control import build_production_execution_context
        context = build_production_execution_context(ctx)
        expected = executable_semantic_fingerprint(effective_persisted_executable(ctx), context)
    else:
        expected = str(configured)
    ctx.expected_execution_fingerprint = expected
    if getattr(ctx, "mode", "").lower() == "es":
        cfg.setdefault("rerun", {})["execution_fingerprint"] = expected
    else:
        cfg.setdefault("semantic_freshness", {})["execution_fingerprint"] = expected
    if auto:
        ctx._computed_persisted_execution_fingerprint = expected
    return expected
