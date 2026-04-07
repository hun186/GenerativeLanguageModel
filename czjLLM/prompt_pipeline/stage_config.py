from __future__ import annotations

from typing import Any


VALID_PERSIST = {"final", "always", "never"}
VALID_ROUTE_VALUE_MODE = {"task_key", "task"}


def _normalize_stage_item(item: Any, index: int, defaults: dict[str, Any]) -> dict[str, Any]:
    # 最短寫法：直接給 task 字串
    if isinstance(item, str):
        return {
            "name": f"stage_{index + 1}",
            "task": item,
            "input_from": str(defaults.get("input_from", "original")),
            "persist_output": str(defaults.get("persist_output", "final")),
        }

    if not isinstance(item, dict):
        raise TypeError(f"不支援的 stage 型別: {type(item)!r}")

    # shorthand: {"translate": "翻成中文"} => name/task
    if "task" not in item and len(item) == 1 and "name" not in item:
        k, v = next(iter(item.items()))
        if isinstance(v, str):
            item = {"name": k, "task": v}

    name = str(item.get("name", "")).strip() or f"stage_{index + 1}"
    task = str(item.get("task", "")).strip()
    task_key = str(item.get("task_key", defaults.get("task_key", ""))).strip()
    if not task and not task_key and "name" in item:
        # 允許用 stage name 對映 taskSetting key（由 orchestrator 解析）
        task_key = name
    if not task and not task_key:
        raise ValueError(f"Stage {index + 1} 缺少 task 或 task_key")

    input_from = str(
        item.get("input_from", item.get("from", defaults.get("input_from", "original")))
    ).strip() or "original"
    persist_output = str(
        item.get("persist_output", item.get("persist", defaults.get("persist_output", "final")))
    ).strip() or "final"
    max_attempts = int(item.get("max_attempts", defaults.get("max_attempts", 2)) or 2)
    route_by = str(item.get("route_by", defaults.get("route_by", ""))).strip()
    route_map = item.get("route_map", defaults.get("route_map"))
    route_value_mode = str(item.get("route_value_mode", defaults.get("route_value_mode", "task_key"))).strip() or "task_key"
    retry_source_on_route_miss = bool(
        item.get("retry_source_on_route_miss", defaults.get("retry_source_on_route_miss", False))
    )

    if persist_output not in VALID_PERSIST:
        raise ValueError(f"Stage {name} persist_output 不合法: {persist_output}")
    if max_attempts < 1:
        raise ValueError(f"Stage {name} max_attempts 必須 >= 1")
    if route_map is not None and not isinstance(route_map, dict):
        raise ValueError(f"Stage {name} route_map 必須是 dict")
    if route_value_mode not in VALID_ROUTE_VALUE_MODE:
        raise ValueError(f"Stage {name} route_value_mode 不合法: {route_value_mode}")

    return {
        "name": name,
        "task": task,
        "task_key": task_key,
        "input_from": input_from,
        "persist_output": persist_output,
        "max_attempts": max_attempts,
        "route_by": route_by,
        "route_map": route_map or {},
        "route_value_mode": route_value_mode,
        "retry_source_on_route_miss": retry_source_on_route_miss,
    }


def normalize_human_stage_spec(task_or_stages: Any) -> list[dict[str, Any]]:
    """
    將人類可讀配置正規化成 stage dict list。

    支援：
    1) 單一 task 字串
    2) list[str|dict]
    3) dict 形式：
       {
         "defaults": {"input_from": "original", "persist_output": "final"},
         "stages": [...]
       }
    """
    defaults: dict[str, Any] = {}
    if isinstance(task_or_stages, dict):
        if "stages" in task_or_stages:
            defaults = dict(task_or_stages.get("defaults") or {})
            raw_stages = task_or_stages.get("stages") or []
        else:
            raw_stages = [task_or_stages]
    elif isinstance(task_or_stages, list):
        raw_stages = task_or_stages
    else:
        raw_stages = [task_or_stages]

    out = [_normalize_stage_item(item, i, defaults) for i, item in enumerate(raw_stages) if item]
    if not out:
        raise ValueError("至少需要 1 個有效階段")

    names = [s["name"] for s in out]
    if len(set(names)) != len(names):
        raise ValueError("stage name 不可重複")
    return out
