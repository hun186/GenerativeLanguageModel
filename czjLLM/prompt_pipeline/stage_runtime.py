from __future__ import annotations

import re
from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import Any
from czjLLM.prompt_pipeline.stage_config import normalize_human_stage_spec


@dataclass(frozen=True)
class StageDefinition:
    """單一階段定義。"""

    name: str
    task: Any
    task_key: str = ""
    input_from: str = "original"   # original | previous | <stage_name>
    persist_output: str = "final"  # final | always | never
    max_attempts: int = 2
    route_by: str = ""             # 讀取哪個階段輸出作為 route key
    route_map: dict[str, str] | None = None  # key -> task template
    route_value_mode: str = "task_key"  # task_key | task
    retry_source_on_route_miss: bool = False
    debug_print_llm_io: bool = False      # 是否印出送 LLM 與回傳內容
    debug_print_max_chars: int = 2000     # debug 輸出最大字元（<=0 代表完整輸出）


@dataclass
class StageStatus:
    """切片在特定階段的執行狀態。"""

    state: str = "pending"
    attempts: int = 0
    last_error: str = ""


@dataclass
class ChunkStageRuntime:
    """單一切片的多階段執行狀態。"""

    chunk_id: str
    stages: dict[str, StageStatus] = field(default_factory=dict)

    def mark_started(self, stage_name: str) -> None:
        status = self.stages.setdefault(stage_name, StageStatus())
        status.state = "running"
        status.attempts += 1

    def mark_success(self, stage_name: str) -> None:
        status = self.stages.setdefault(stage_name, StageStatus())
        status.state = "success"
        status.last_error = ""

    def mark_failed(self, stage_name: str, error: str) -> None:
        status = self.stages.setdefault(stage_name, StageStatus())
        status.state = "failed"
        status.last_error = error

    def mark_error(self, stage_name: str, error: str) -> None:
        status = self.stages.setdefault(stage_name, StageStatus())
        status.state = "error"
        status.last_error = error

    def next_runnable_stage(self, stage_order: list[str]) -> str | None:
        for stage_name in stage_order:
            status = self.stages.get(stage_name)
            if status is None or status.state in {"pending", "failed"}:
                return stage_name
            if status.state != "success":
                return None
        return None


@dataclass
class StageDispatchJob:
    """可由既有 worker 執行器消費的最小派工描述。"""

    chunk_id: str
    stage_name: str
    stage_task: Any
    input_from: str = "original"


def _as_stage_definition(item: Any, index: int) -> StageDefinition:
    if isinstance(item, StageDefinition):
        return item
    if isinstance(item, str):
        name = f"stage_{index + 1}"
        return StageDefinition(name=name, task=item)
    if isinstance(item, dict):
        raw_task = item.get("task", "")
        task = raw_task if isinstance(raw_task, Mapping) else str(raw_task).strip()
        task_key = str(item.get("task_key", "")).strip()
        name = str(item.get("name", "")).strip() or f"stage_{index + 1}"
        input_from_raw = item.get("input_from", "original")
        input_from = "" if input_from_raw is None else str(input_from_raw).strip()
        persist_output = str(item.get("persist_output", "final")).strip() or "final"
        max_attempts = int(item.get("max_attempts", 2) or 2)
        route_by = str(item.get("route_by", "")).strip()
        route_map = item.get("route_map")
        route_value_mode = str(item.get("route_value_mode", "task_key")).strip() or "task_key"
        retry_source_on_route_miss = bool(item.get("retry_source_on_route_miss", False))
        debug_print_llm_io = bool(item.get("debug_print_llm_io", False))
        debug_print_max_chars = int(item.get("debug_print_max_chars", 2000) or 2000)
        if not task and not task_key:
            raise ValueError(f"Stage {index + 1} 缺少 task 或 task_key")
        return StageDefinition(
            name=name,
            task=task,
            task_key=task_key,
            input_from=input_from,
            persist_output=persist_output,
            max_attempts=max_attempts,
            route_by=route_by,
            route_map=route_map if isinstance(route_map, dict) else None,
            route_value_mode=route_value_mode,
            retry_source_on_route_miss=retry_source_on_route_miss,
            debug_print_llm_io=debug_print_llm_io,
            debug_print_max_chars=debug_print_max_chars,
        )
    raise TypeError(f"不支援的 stage 型別: {type(item)!r}")


def normalize_stages(task_or_stages: Any) -> list[StageDefinition]:
    """
    兼容舊架構（單一 task 字串）與新架構（多階段設定）。
    回傳至少 1 個 StageDefinition。
    """

    normalized = normalize_human_stage_spec(task_or_stages)
    stages = [_as_stage_definition(item, i) for i, item in enumerate(normalized)]
    if not stages:
        raise ValueError("至少需要 1 個有效階段")
    return stages


def build_chunk_stage_runtime(chunk_ids: list[str], stages: list[StageDefinition]) -> dict[str, ChunkStageRuntime]:
    """建立切片 x 階段 的初始狀態矩陣。"""

    stage_names = [s.name for s in stages]
    runtime: dict[str, ChunkStageRuntime] = {}
    for chunk_id in chunk_ids:
        chunk_runtime = ChunkStageRuntime(chunk_id=chunk_id)
        for stage_name in stage_names:
            chunk_runtime.stages[stage_name] = StageStatus()
        runtime[chunk_id] = chunk_runtime
    return runtime


def build_dispatch_jobs(
    runtime: dict[str, ChunkStageRuntime],
    stages: list[StageDefinition],
) -> list[StageDispatchJob]:
    """
    依照階段順序建立「下一批可派工」工作。
    規則：
    - 每個 chunk 一次只會派出 1 個階段（避免跨階段並行造成資料覆寫）。
    - 只派 pending/failed 的下一階段。
    """

    stage_by_name = {s.name: s for s in stages}
    stage_order = [s.name for s in stages]
    jobs: list[StageDispatchJob] = []

    for chunk_id in sorted(runtime.keys()):
        chunk_runtime = runtime[chunk_id]
        stage_name = chunk_runtime.next_runnable_stage(stage_order)
        if stage_name is None:
            continue
        stage_def = stage_by_name[stage_name]
        jobs.append(
            StageDispatchJob(
                chunk_id=chunk_id,
                stage_name=stage_name,
                stage_task=stage_def.task,
                input_from=stage_def.input_from,
            )
        )
    return jobs


def apply_dispatch_results(
    runtime: dict[str, ChunkStageRuntime],
    results: list[dict[str, Any]],
) -> None:
    """
    將 worker 回報套用到 runtime。
    result 格式:
      {"chunk_id":"c1","stage_name":"extract","ok":True}
      {"chunk_id":"c1","stage_name":"extract","ok":False,"error":"timeout"}
    """

    for item in results:
        chunk_id = str(item["chunk_id"])
        stage_name = str(item["stage_name"])
        ok = bool(item.get("ok"))
        chunk_runtime = runtime[chunk_id]
        current = chunk_runtime.stages.get(stage_name)
        if current is not None and current.state == "error":
            continue
        if ok:
            chunk_runtime.mark_success(stage_name)
        else:
            chunk_runtime.mark_failed(stage_name, str(item.get("error", "")))


def is_chunk_finished(chunk_runtime: ChunkStageRuntime, stage_order: list[str]) -> bool:
    """判斷單一 chunk 是否全部階段成功。"""
    for stage_name in stage_order:
        status = chunk_runtime.stages.get(stage_name)
        if status is None or status.state != "success":
            return False
    return True


def summarize_runtime(
    runtime: dict[str, ChunkStageRuntime],
    stage_order: list[str],
) -> dict[str, int]:
    """
    回傳整體執行摘要：
    - finished_chunks: 全階段成功的 chunk 數
    - blocked_chunks: 當前沒有可派工階段且未完成（通常表示某階段 running）
    - pending_jobs: 下一輪可派工數量
    """
    finished = 0
    blocked = 0
    pending_jobs = 0
    for chunk_runtime in runtime.values():
        if is_chunk_finished(chunk_runtime, stage_order):
            finished += 1
            continue
        nxt = chunk_runtime.next_runnable_stage(stage_order)
        if nxt is None:
            blocked += 1
        else:
            pending_jobs += 1
    return {
        "finished_chunks": finished,
        "blocked_chunks": blocked,
        "pending_jobs": pending_jobs,
    }


def resolve_stage_input(
    stage: StageDefinition,
    stage_order: list[str],
    outputs_by_stage: dict[str, str],
    original_text: str,
) -> str:
    """
    決定某階段的輸入來源：
    - original: 使用原文
    - previous: 使用前一階段輸出（沒有就 fallback 原文）
    - none / 空字串: 不帶入來源文字（僅送出模板）
    - <stage_name>: 使用指定階段輸出（沒有就 fallback 原文）
    """
    source = stage.input_from
    if source in {"", "none", "null"}:
        return ""
    if source == "original":
        return original_text
    if source == "previous":
        try:
            idx = stage_order.index(stage.name)
            if idx <= 0:
                return original_text
            prev_name = stage_order[idx - 1]
            return outputs_by_stage.get(prev_name, original_text)
        except ValueError:
            return original_text
    return outputs_by_stage.get(source, original_text)


def should_persist_output(stage: StageDefinition, last_stage_name: str) -> bool:
    policy = stage.persist_output
    if policy == "always":
        return True
    if policy == "never":
        return False
    # final (default)
    return stage.name == last_stage_name


def resolve_stage_task(
    stage: StageDefinition,
    outputs_by_stage: dict[str, str],
    task_setting: dict[str, Any] | None = None,
) -> tuple[Any, str | None]:
    """
    回傳 (task, err)
    - 無 route_map 時回傳原 task
    - 有 route_map 時用 route_by 對應輸出決定 task
    """
    def _resolve_task_setting_entry(entry: Any) -> Any:
        if isinstance(entry, Mapping):
            return entry
        return str(entry or "").strip()

    def _effective_task_setting(explicit: dict[str, Any] | None) -> dict[str, Any] | None:
        if isinstance(explicit, dict) and explicit:
            return explicit
        try:
            from czjLLM.taskConfig import taskSetting as global_task_setting
        except Exception:
            return explicit if isinstance(explicit, dict) else None
        return global_task_setting if isinstance(global_task_setting, dict) else None

    task_setting = _effective_task_setting(task_setting)

    if not stage.route_map:
        return stage.task, None
    route_key_raw = outputs_by_stage.get(stage.route_by, "")

    def _route_candidates(value: object) -> list[str]:
        text = str(value or "").strip()
        if not text:
            return []
        # 1) 原字串（完整匹配）
        out = [text]
        # 2) 常見分類器輸出會帶句尾符號（org. / other。 / `org`）
        stripped = text.strip("`'\"[](){}<>,.;:!?，。！？；：")
        if stripped and stripped not in out:
            out.append(stripped)
        # 3) 常見分類器會附註說明，保留第一個 token 嘗試匹配
        first = stripped.split()[0] if stripped.split() else ""
        if first and first not in out:
            out.append(first)
        # 3.5) 若第一個 token 仍帶標點，擷取英數底線分類碼（如：ORG。說明）
        m = re.search(r"[A-Za-z_][A-Za-z0-9_]*", stripped)
        if m:
            lex = m.group(0)
            if lex not in out:
                out.append(lex)
        # 4) 大小寫不一致時，嘗試 lower（例如 ORG）
        lower_keys = [x.lower() for x in list(out)]
        for x in lower_keys:
            if x and x not in out:
                out.append(x)
        return out

    route_key = ""
    for cand in _route_candidates(route_key_raw):
        if cand in stage.route_map:
            route_key = cand
            break

    if route_key:
        mapped_raw = stage.route_map[route_key]
        if isinstance(mapped_raw, Mapping):
            mapped_task = mapped_raw.get("task", mapped_raw.get("prompt", mapped_raw.get("template", "")))
            if mapped_task == "":
                return mapped_raw, None
            mapped = str(mapped_task).strip()
        else:
            mapped = str(mapped_raw).strip()

        if mapped.startswith("@taskSetting:"):
            key = mapped.split(":", 1)[1].strip()
            if task_setting and key in task_setting:
                return _resolve_task_setting_entry(task_setting[key]), None
            return "", f"task_key_missing:{key}"
        if stage.route_value_mode == "task_key":
            if task_setting and mapped in task_setting:
                return _resolve_task_setting_entry(task_setting[mapped]), None
            return "", f"task_key_missing:{mapped}"
        if isinstance(mapped_raw, Mapping):
            out = dict(mapped_raw)
            out["task"] = mapped
            return out, None
        return mapped, None
    return stage.task, f"route_miss:{stage.route_by}:{str(route_key_raw or '').strip()}"
