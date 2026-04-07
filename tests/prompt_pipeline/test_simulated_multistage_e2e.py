from dataclasses import dataclass, field

from czjLLM.prompt_pipeline import stage_orchestrator as so


def _chunk_text(text: str) -> list[str]:
    # 測試用：極簡切片
    return [part.strip() for part in text.split("||") if part.strip()]


@dataclass
class SimCtx:
    stages: list[dict] = field(
        default_factory=lambda: [
            {"name": "route", "task_key": "分類判定", "persist_output": "always"},
            {
                "name": "apply_template",
                "task": "fallback",
                "input_from": "original",
                "route_by": "route",
                "route_map": {"FIN": "模板_財務", "LEGAL": "模板_法務"},
                # 預設 task_key mode：route_map value 會去 taskSetting 取真正 task
                "persist_output": "final",
                "retry_source_on_route_miss": True,
                "max_attempts": 2,
            },
        ]
    )
    taskSetting: dict = field(
        default_factory=lambda: {
            "分類判定": "請輸出 FIN 或 LEGAL",
            "模板_財務": "請用財務模板產出摘要",
            "模板_法務": "請用法務模板產出摘要",
        }
    )


def test_simulated_e2e_text_chunk_multistage_merge():
    text = "finance report Q1 || legal dispute summary"
    chunks = _chunk_text(text)
    chunk_ids = [f"chunk_{i}" for i in range(len(chunks))]
    original_inputs = dict(zip(chunk_ids, chunks))

    ctx = SimCtx()
    runtime = so.init_chunk_stage_runtime(ctx, chunk_ids)
    llm_io_log = []

    def fake_runner(job, _ctx, input_text):
        llm_io_log.append(
            {
                "chunk_id": job.chunk_id,
                "stage": job.stage_name,
                "task": job.stage_task,      # 模擬 LLM 的實際 prompt/task
                "input": input_text,         # 模擬 LLM 的實際輸入
            }
        )
        if job.stage_name == "route":
            label = "FIN" if "finance" in input_text else "LEGAL"
            return {"ok": True, "output": label}

        # apply_template：回傳最終可合併輸出
        return {"ok": True, "output": f"[{job.stage_task}] {input_text}"}

    report = so.run_stage_pipeline(
        ctx,
        runtime,
        fake_runner,
        max_rounds=5,
        original_inputs=original_inputs,
    )

    # 驗證流程收斂
    assert report["final"]["finished_chunks"] == 2

    # 驗證 LLM 模擬輸入/輸出傳遞正確（第二階段拿原文，但 task 已依路由切換）
    chunk0_apply = [x for x in llm_io_log if x["chunk_id"] == "chunk_0" and x["stage"] == "apply_template"][0]
    chunk1_apply = [x for x in llm_io_log if x["chunk_id"] == "chunk_1" and x["stage"] == "apply_template"][0]
    assert chunk0_apply["task"] == "請用財務模板產出摘要"
    assert chunk1_apply["task"] == "請用法務模板產出摘要"

    # 模擬「合併」：收集每個 chunk 最終持久化輸出
    merged = "\n".join(
        report["persisted_outputs"][cid]["apply_template"]
        for cid in chunk_ids
    )
    assert "請用財務模板產出摘要" in merged
    assert "請用法務模板產出摘要" in merged


def test_simulated_router_retry_on_unexpected_class():
    text = "finance memo"
    chunk_ids = ["chunk_0"]
    original_inputs = {"chunk_0": text}
    ctx = SimCtx()
    runtime = so.init_chunk_stage_runtime(ctx, chunk_ids)

    route_outputs = iter(["UNKNOWN", "FIN"])  # 第一次路由失敗，第二次成功

    def fake_runner(job, _ctx, input_text):
        if job.stage_name == "route":
            return {"ok": True, "output": next(route_outputs)}
        return {"ok": True, "output": f"[{job.stage_task}] {input_text}"}

    report = so.run_stage_pipeline(
        ctx,
        runtime,
        fake_runner,
        max_rounds=6,
        original_inputs=original_inputs,
    )

    assert report["final"]["finished_chunks"] == 1
    assert "apply_template" in report["persisted_outputs"]["chunk_0"]
