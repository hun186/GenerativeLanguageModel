from __future__ import annotations

from dataclasses import dataclass, replace
from collections.abc import Mapping
from typing import Callable

from czjLLM.prompt_pipeline.stage_runtime import (
    ChunkStageRuntime,
    StageDefinition,
    apply_dispatch_results,
    build_chunk_stage_runtime,
    build_dispatch_jobs,
    normalize_stages,
    resolve_stage_input,
    resolve_stage_task,
    should_persist_output,
    summarize_runtime,
)

def _stage_task_debug_preview(task: object, max_len: int = 300) -> str:
    if isinstance(task, Mapping):
        task_text = str(task.get("task", ""))
        preview = f"<mapping> keys={sorted(task.keys())} task={task_text!r}"
    else:
        preview = str(task)
    preview = preview.replace("\n", "\\n")
    if len(preview) > max_len:
        return preview[:max_len] + "...<truncated>"
    return preview


@dataclass
class StageRoundResult:
    dispatched_jobs: int
    finished_chunks: int
    blocked_chunks: int
    pending_jobs: int

    def as_dict(self) -> dict:
        return {
            "dispatched_jobs": self.dispatched_jobs,
            "finished_chunks": self.finished_chunks,
            "blocked_chunks": self.blocked_chunks,
            "pending_jobs": self.pending_jobs,
        }


def resolve_pipeline_stages(ctx) -> list[StageDefinition]:
    raw_stages = getattr(ctx, "stages", None)
    if raw_stages is None:
        task_config = getattr(ctx, "task_config", None)
        if isinstance(task_config, dict) and "stages" in task_config:
            raw_stages = task_config
        else:
            raw_stages = getattr(ctx, "task", "")
    stages = normalize_stages(raw_stages)
    task_setting = getattr(ctx, "taskSetting", None)
    if not isinstance(task_setting, Mapping):
        return stages

    def _resolve_task_setting_entry(entry):
        if isinstance(entry, Mapping):
            return entry
        return str(entry or "").strip()

    resolved: list[StageDefinition] = []
    for stage in stages:
        task_text = stage.task
        task_key = stage.task_key

        # 1) 明確指定 task_key
        if task_key:
            mapped = task_setting.get(task_key, task_text)
            task_text = _resolve_task_setting_entry(mapped)
        # 2) task 為 @taskSetting:key 形式
        elif isinstance(task_text, str) and task_text.startswith("@taskSetting:"):
            key = task_text.split(":", 1)[1].strip()
            mapped = task_setting.get(key, "")
            task_text = _resolve_task_setting_entry(mapped)
        # 3) 若 task 留空，預設用 stage.name 對映 taskSetting
        elif not task_text:
            mapped = task_setting.get(stage.name, "")
            task_text = _resolve_task_setting_entry(mapped)

        # 允許「純路由階段」不提供預設 task：
        # 該階段會在執行時由 route_map + route_by 動態決定 task。
        if not task_text and not stage.route_map:
            raise ValueError(f"Stage '{stage.name}' 無法從 taskSetting 解析 task")
        resolved.append(replace(stage, task=task_text))

    return resolved


def init_chunk_stage_runtime(ctx, chunk_ids: list[str]) -> dict[str, ChunkStageRuntime]:
    stages = resolve_pipeline_stages(ctx)
    return build_chunk_stage_runtime(chunk_ids, stages)


def plan_chunk_stage_dispatch(ctx, runtime: dict[str, ChunkStageRuntime]):
    stages = resolve_pipeline_stages(ctx)
    return build_dispatch_jobs(runtime, stages)


def update_chunk_stage_runtime(runtime: dict[str, ChunkStageRuntime], results: list[dict]):
    apply_dispatch_results(runtime, results)


def execute_stage_round(
    ctx,
    runtime: dict[str, ChunkStageRuntime],
    runner: Callable,
    stage_outputs: dict[str, dict[str, str]] | None = None,
    original_inputs: dict[str, str] | None = None,
    persisted_outputs: dict[str, dict[str, str]] | None = None,
) -> StageRoundResult:
    jobs = plan_chunk_stage_dispatch(ctx, runtime)
    results: list[dict] = []
    stage_outputs = stage_outputs if stage_outputs is not None else {}
    original_inputs = original_inputs if original_inputs is not None else {}
    persisted_outputs = persisted_outputs if persisted_outputs is not None else {}
    task_setting = getattr(ctx, "taskSetting", None)
    task_setting = task_setting if isinstance(task_setting, Mapping) else None
    stages = resolve_pipeline_stages(ctx)
    stage_order = [s.name for s in stages]
    stage_map = {s.name: s for s in stages}
    for job in jobs:
        chunk_runtime = runtime[job.chunk_id]
        chunk_stage_outputs = stage_outputs.setdefault(job.chunk_id, {})
        original_text = original_inputs.get(job.chunk_id, "")
        stage_def = stage_map[job.stage_name]
        chunk_runtime.mark_started(job.stage_name)
        effective_task, route_err = resolve_stage_task(stage_def, chunk_stage_outputs, task_setting=task_setting)
        if stage_def.debug_print_llm_io:
            print(
                f"[stage:{job.stage_name}] 🔎 resolved task preview: "
                f"{_stage_task_debug_preview(effective_task)}"
            )
        if route_err:
            # 只有 route key 無法匹配時才回退重跑 route_by 來源 stage；
            # taskSetting 缺漏等配置錯誤不應造成 route stage 反覆重跑。
            should_retry_source = route_err.startswith("route_miss:")
            if should_retry_source and stage_def.retry_source_on_route_miss and stage_def.route_by in chunk_runtime.stages:
                chunk_runtime.mark_failed(stage_def.route_by, route_err)
                chunk_stage_outputs.pop(stage_def.route_by, None)
            chunk_runtime.mark_failed(job.stage_name, route_err)
            # 若此階段嘗試次數已耗盡，轉為 error，避免無限重試
            status = chunk_runtime.stages.get(job.stage_name)
            if status and status.attempts >= stage_def.max_attempts:
                chunk_runtime.mark_error(job.stage_name, route_err)
            results.append(
                {
                    "chunk_id": job.chunk_id,
                    "stage_name": job.stage_name,
                    "ok": False,
                    "error": route_err,
                }
            )
            continue


        effective_input_from = stage_def.input_from
        if isinstance(effective_task, dict):
            route_input_from_raw = effective_task.get("input_from", effective_task.get("from", effective_input_from))
            effective_input_from = "" if route_input_from_raw is None else str(route_input_from_raw).strip()

        routed_job = type(job)(
            chunk_id=job.chunk_id,
            stage_name=job.stage_name,
            stage_task=effective_task,
            input_from=effective_input_from,
        )
        input_text = resolve_stage_input(
            stage=type(stage_def)(**{**stage_def.__dict__, "input_from": effective_input_from}),
            stage_order=stage_order,
            outputs_by_stage=chunk_stage_outputs,
            original_text=original_text,
        )
        try:
            raw = runner(routed_job, ctx, input_text)
        except TypeError:
            raw = runner(routed_job, ctx)
        if isinstance(raw, dict):
            ok = bool(raw.get("ok"))
            error = str(raw.get("error", ""))
            output_text = raw.get("output")
        else:
            ok = bool(raw)
            error = ""
            output_text = None
        if ok and isinstance(output_text, str):
            chunk_stage_outputs[job.stage_name] = output_text
            if should_persist_output(stage_def, last_stage_name=stage_order[-1]):
                persisted_outputs.setdefault(job.chunk_id, {})[job.stage_name] = output_text
        elif not ok:
            status = chunk_runtime.stages.get(job.stage_name)
            if status and status.attempts >= stage_def.max_attempts:
                chunk_runtime.mark_error(job.stage_name, error or "max_attempts_exceeded")
        results.append(
            {
                "chunk_id": job.chunk_id,
                "stage_name": job.stage_name,
                "ok": ok,
                "error": error,
            }
        )

    if results:
        update_chunk_stage_runtime(runtime, results)

    summary = summarize_runtime(runtime, stage_order)
    return StageRoundResult(
        dispatched_jobs=len(jobs),
        finished_chunks=summary["finished_chunks"],
        blocked_chunks=summary["blocked_chunks"],
        pending_jobs=summary["pending_jobs"],
    )


def run_stage_pipeline(
    ctx,
    runtime: dict[str, ChunkStageRuntime],
    runner: Callable,
    max_rounds: int = 20,
    original_inputs: dict[str, str] | None = None,
):
    rounds: list[dict] = []
    stage_outputs: dict[str, dict[str, str]] = {}
    persisted_outputs: dict[str, dict[str, str]] = {}
    for round_idx in range(1, max_rounds + 1):
        summary = execute_stage_round(
            ctx,
            runtime,
            runner,
            stage_outputs=stage_outputs,
            original_inputs=original_inputs,
            persisted_outputs=persisted_outputs,
        ).as_dict()
        summary["round"] = round_idx
        rounds.append(summary)

        if summary["finished_chunks"] == len(runtime):
            break
        if summary["dispatched_jobs"] == 0:
            break

    return {
        "rounds": rounds,
        "final": rounds[-1] if rounds else {
            "round": 0,
            "finished_chunks": 0,
            "blocked_chunks": 0,
            "pending_jobs": 0,
            "dispatched_jobs": 0,
        },
        "max_rounds_reached": bool(rounds and rounds[-1]["round"] >= max_rounds),
        "persisted_outputs": persisted_outputs,
        "stage_outputs": stage_outputs,
    }
