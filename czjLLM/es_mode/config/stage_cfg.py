"""Helpers for carrying ES multi-stage ``stage_cfg`` through runtime config.

``stage_cfg`` follows the existing multistage naming used by
``infer_multistage_task_hint(stage_cfg)``: it is the YAML-declared stage flow,
usually shaped as either a dict containing ``stages`` or a plain list of stages.

This module deliberately does not execute stages yet.  It only normalizes the
stage declaration so the future ES multistage executor can consume the same
concept as other modes.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Dict, List, Mapping, Optional

STAGE_CFG_SECTION_KEYS = (
    "router",
    "routes",
    "stages",
    "steps",
    "stage_outputs",
    "default_route",
    "route_field",
)


def _safe_get_param(get_param: Callable[[str, Any], Any], key: str, default: Any = None) -> Any:
    try:
        return get_param(key, default)
    except TypeError:
        value = get_param(key)
        return default if value is None else value


def _as_dict(value: Any) -> Dict[str, Any]:
    return deepcopy(value) if isinstance(value, dict) else {}


def build_es_stage_cfg(
    get_param: Callable[[str, Any], Any],
    es_cfg: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Normalize ES route/stage YAML into a single ``stage_cfg`` dict.

    Preferred cross-mode YAML shape is one of::

        stage_cfg:
          stages: [...]

    or::

        stages: [...]

    ``steps`` is accepted as a shorthand alias for ``stages`` because existing
    architecture notes use both words.  ``pipeline_name`` is still accepted only
    as the flow name metadata; it does not imply a separate ``stage_cfg``
    object.
    """
    es_cfg = dict(es_cfg or {})

    raw_stage_cfg = _safe_get_param(get_param, "stage_cfg", None)
    if raw_stage_cfg is None:
        raw_stage_cfg = es_cfg.get("stage_cfg")

    stage_cfg = _as_dict(raw_stage_cfg)
    explicit = isinstance(raw_stage_cfg, dict)

    if isinstance(raw_stage_cfg, list):
        stage_cfg = {"stages": deepcopy(raw_stage_cfg)}
        explicit = True

    for key in STAGE_CFG_SECTION_KEYS:
        value = _safe_get_param(get_param, key, None)
        if value is not None:
            explicit = True
            if key not in stage_cfg:
                stage_cfg[key] = deepcopy(value)

    for key in ("pipeline_name", "pipeline_version", "pipeline_hash"):
        value = _safe_get_param(get_param, key, None)
        if value is not None:
            explicit = True
            normalized_key = "name" if key == "pipeline_name" else key.replace("pipeline_", "")
            if normalized_key not in stage_cfg:
                stage_cfg[normalized_key] = deepcopy(value)

    for key in (*STAGE_CFG_SECTION_KEYS, "pipeline_name", "pipeline_version", "pipeline_hash"):
        value = es_cfg.get(key)
        if value is None:
            continue
        explicit = True
        normalized_key = "name" if key == "pipeline_name" else key.replace("pipeline_", "")
        stage_cfg.setdefault(normalized_key, deepcopy(value))

    if not explicit:
        return {}

    if "stages" not in stage_cfg and "steps" in stage_cfg:
        stage_cfg["stages"] = deepcopy(stage_cfg["steps"])

    has_flow = any(k in stage_cfg for k in ("router", "routes", "stages", "steps"))
    if "enabled" not in stage_cfg:
        stage_cfg["enabled"] = bool(has_flow)

    if not stage_cfg.get("name"):
        stage_cfg["name"] = "single_stage" if not stage_cfg.get("enabled") else "es_multistage"

    return stage_cfg


def stage_name_from_cfg(stage_cfg: Mapping[str, Any], fallback: Optional[str] = None) -> Optional[str]:
    name = stage_cfg.get("name") if isinstance(stage_cfg, Mapping) else None
    return str(name) if name else fallback



def _stage_es_options(stage: Mapping[str, Any]) -> Dict[str, Any]:
    """Return ES-specific options declared on a single stage.

    A stage may put these keys directly on the stage or under an ``es`` block.
    The nested block wins, so YAML can keep ES routing/mapping details grouped::

        - name: extract
          output_col: result_json
          es:
            src_index: source_a
            tgt_index: result_a
            mapping_file: czjLLM/config_es/schemas/result_a.yaml
    """
    direct = {
        key: stage.get(key)
        for key in (
            "src_index",
            "tgt_index",
            "input_col",
            "output_col",
            "output_profile",
            "mapping_file",
            "es_apply_mapping",
            "es_output_type",
            "meta_field",
            "write_output",
            "write_meta",
            "persist_output",
        )
        if stage.get(key) is not None
    }
    nested = stage.get("es") if isinstance(stage.get("es"), Mapping) else {}
    return {**direct, **dict(nested)}


def collect_stage_es_bindings(
    stage_cfg: Mapping[str, Any],
    *,
    default_src_index: Optional[str] = None,
    default_tgt_index: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Collect per-stage ES index/mapping declarations without executing them.

    This is the bridge needed by the future ES multistage executor: each returned
    binding says which stage wants which source/target index, output field,
    output profile, and mapping file.  Missing indexes are filled from the
    current adapter-level defaults.
    """
    if not isinstance(stage_cfg, Mapping):
        return []

    root_defaults = _stage_es_options(stage_cfg)
    if default_src_index is not None:
        root_defaults.setdefault("src_index", default_src_index)
    if default_tgt_index is not None:
        root_defaults.setdefault("tgt_index", default_tgt_index)

    bindings: List[Dict[str, Any]] = []

    def visit(stage: Any, route: Optional[str] = None, role: str = "stage") -> None:
        if not isinstance(stage, Mapping):
            return
        opts = {**root_defaults, **_stage_es_options(stage)}
        binding = {
            "stage_name": stage.get("name") or stage.get("task") or role,
            "route": route,
            "role": role,
            **{k: v for k, v in opts.items() if v is not None},
        }
        # Keep only stages that actually declare or inherit ES sink/index/write info.
        if any(k in binding for k in ("src_index", "tgt_index", "output_col", "mapping_file", "write_output")):
            bindings.append(binding)

    router = stage_cfg.get("router")
    if isinstance(router, Mapping):
        visit(router, role="router")

    for stage in stage_cfg.get("stages") or []:
        visit(stage)

    routes = stage_cfg.get("routes") or {}
    if isinstance(routes, Mapping):
        for route_name, route_cfg in routes.items():
            if not isinstance(route_cfg, Mapping):
                continue
            for stage in route_cfg.get("stages") or []:
                visit(stage, route=str(route_name))

    return bindings
