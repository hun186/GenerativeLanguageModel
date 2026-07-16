"""Helpers for deciding whether stream rows are managed by stage runtime."""

from collections.abc import Mapping
from typing import Any


def stage_cfg_declares_flow(stage_cfg) -> bool:
    """Return True only when ``stage_cfg`` explicitly declares runnable stages/routes.

    ES config normalization always attaches a compatibility ``stage_cfg`` dict
    (for example ``{enabled: False, name: single_stage}``) even for legacy
    single-stage YAML files. Such metadata must not disable the normal stream
    consumer; only an enabled stage config or actual route/stage declarations are
    stage-managed by ``process_prompt_and_merge``.
    """
    if not isinstance(stage_cfg, Mapping):
        return False
    if bool(stage_cfg.get("enabled", False)):
        return True
    for key in ("stages", "steps"):
        value = stage_cfg.get(key)
        if isinstance(value, list) and len(value) > 0:
            return True
    routes = stage_cfg.get("routes")
    if isinstance(routes, Mapping) and len(routes) > 0:
        return True
    router = stage_cfg.get("router")
    if isinstance(router, Mapping) and len(router) > 0:
        return True
    return False


def explicit_stage_flow(ctx: Any | None) -> list[dict]:
    """Return explicitly configured stages from ``ctx`` without promoting plain tasks.

    ``resolve_pipeline_stages(ctx)`` intentionally turns a legacy single
    ``ctx.task`` into a one-stage pipeline for compatibility.  Stream scheduling
    and final prompt merging need a stricter signal: only YAML-declared
    ``stages`` (or ``task_config.stages``) mean the row is stage-managed.
    """
    if ctx is None:
        return []
    stages = getattr(ctx, "stages", None)
    if isinstance(stages, list) and len(stages) > 0:
        return [stage for stage in stages if isinstance(stage, dict)]
    task_config = getattr(ctx, "task_config", None)
    if isinstance(task_config, Mapping):
        task_stages = task_config.get("stages")
        if isinstance(task_stages, list) and len(task_stages) > 0:
            return [stage for stage in task_stages if isinstance(stage, dict)]
    return []
