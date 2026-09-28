"""Parallelism policy for LLM prompt-slice dispatch."""

from __future__ import annotations

from contextlib import contextmanager

from czjLLM.reduction.execution_budget import ExecutionBudget


SLICE_PARALLELISM_KEYS = (
    "multistage_slice_parallelism",
    "llm_slice_parallelism",
    "slice_parallelism",
)

MODEL_PROCESS_PARALLELISM_KEYS = ("n_process", "nProcess")
ROW_PARALLELISM_KEYS = (
    "multistage_row_parallelism",
    "sql_multistage_row_parallelism",
    "stream_multistage_row_parallelism",
)


def _positive_int(value) -> int:
    if isinstance(value, bool):
        return 0
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def configured_model_process_parallelism(model_spec) -> int:
    """Return an explicit model-profile process budget, or zero for auto mode."""

    if not isinstance(model_spec, dict):
        return 0
    for key in MODEL_PROCESS_PARALLELISM_KEYS:
        value = _positive_int(model_spec.get(key))
        if value > 0:
            return value
    return 0


def resolve_slice_parallelism(ctx, job_count: int) -> int:
    """Return the worker count for one batch of prompt slices.

    Row/doc parallelism controls how many documents may enter the pipeline.  It
    must not also be the only control for the tail of one unusually long
    document, so operators may set a dedicated slice-level value.  Existing
    configurations keep their historical ``ctx.n_process`` behaviour.
    """

    try:
        jobs = max(0, int(job_count))
    except (TypeError, ValueError):
        jobs = 0
    if jobs == 0:
        return 1

    configured = 0
    for key in SLICE_PARALLELISM_KEYS:
        value = _positive_int(getattr(ctx, key, 0))
        if value > 0:
            configured = value
            break

    model_spec = getattr(ctx, "model_spec", None)
    if configured <= 0 and isinstance(model_spec, dict):
        for key in SLICE_PARALLELISM_KEYS:
            value = _positive_int(model_spec.get(key))
            if value > 0:
                configured = value
                break

    if configured <= 0:
        configured = _positive_int(getattr(ctx, "n_process", 1)) or 1

    return max(1, min(configured, jobs))


def _configured_positive(ctx, keys) -> list[int]:
    values = []
    for key in keys:
        value = _positive_int(getattr(ctx, key, 0))
        if value:
            values.append(value)
    return values


def resolve_execution_budget_capacity(ctx) -> int:
    """Resolve root > model explicit capacity, else the widest local policy."""

    marker = object()
    explicit = getattr(ctx, "execution_budget_capacity", marker)
    if explicit is marker:
        model_spec = getattr(ctx, "model_spec", None)
        explicit = (
            model_spec.get("execution_budget_capacity", marker)
            if isinstance(model_spec, dict)
            else marker
        )
    if explicit is not marker:
        if type(explicit) is not int or explicit <= 0:
            raise ValueError("execution_budget_capacity must be a positive integer")
        return explicit

    candidates = _configured_positive(
        ctx, ("n_process",) + ROW_PARALLELISM_KEYS + SLICE_PARALLELISM_KEYS
    )
    model_spec = getattr(ctx, "model_spec", None)
    if isinstance(model_spec, dict):
        for key in MODEL_PROCESS_PARALLELISM_KEYS + SLICE_PARALLELISM_KEYS:
            value = _positive_int(model_spec.get(key))
            if value:
                candidates.append(value)
    return max(candidates, default=1)


def attach_execution_budget(ctx) -> ExecutionBudget:
    """Attach exactly one budget to a root runtime context."""

    if hasattr(ctx, "_execution_budget"):
        return ctx._execution_budget
    budget = ExecutionBudget(resolve_execution_budget_capacity(ctx))
    ctx._execution_budget = budget
    return budget


@contextmanager
def lease_execution_workers(ctx, requested: int):
    """Lease leaf workers, preserving legacy width when no root budget exists."""

    budget = getattr(ctx, "_execution_budget", None)
    if budget is None:
        yield requested
        return
    with budget.lease(requested) as granted:
        yield granted


def cap_orchestration_workers(ctx, desired: int) -> int:
    """Cap thread count only; orchestration must never retain a leaf lease."""

    budget = getattr(ctx, "_execution_budget", None)
    return min(desired, budget.capacity) if budget is not None else desired
