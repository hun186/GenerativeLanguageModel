"""Parallelism policy for LLM prompt-slice dispatch."""

from __future__ import annotations


SLICE_PARALLELISM_KEYS = (
    "multistage_slice_parallelism",
    "llm_slice_parallelism",
    "slice_parallelism",
)

MODEL_PROCESS_PARALLELISM_KEYS = ("n_process", "nProcess")


def _positive_int(value) -> int:
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
