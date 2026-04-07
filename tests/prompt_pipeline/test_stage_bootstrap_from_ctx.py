from dataclasses import dataclass, field

import czjLLM.prompt_pipeline.pipeline_controller as pc


@dataclass
class CtxWithTask:
    task: str = "抽取重點"


@dataclass
class CtxWithStages:
    stages: list[dict[str, str]] = field(
        default_factory=lambda: [
            {"name": "extract", "task": "抽取"},
            {"name": "classify", "task": "分類"},
        ]
    )


@dataclass
class CtxWithTaskConfig:
    task_config: dict = field(default_factory=lambda: {"stages": ["摘要", "翻譯"]})


def test_resolve_pipeline_stages_from_legacy_task():
    stages = pc.resolve_pipeline_stages(CtxWithTask())
    assert len(stages) == 1
    assert stages[0].name == "stage_1"
    assert stages[0].task == "抽取重點"


def test_resolve_pipeline_stages_from_ctx_stages():
    stages = pc.resolve_pipeline_stages(CtxWithStages())
    assert [s.name for s in stages] == ["extract", "classify"]
    assert [s.task for s in stages] == ["抽取", "分類"]


def test_init_chunk_stage_runtime_from_task_config():
    runtime = pc.init_chunk_stage_runtime(CtxWithTaskConfig(), chunk_ids=["c1", "c2"])
    assert set(runtime.keys()) == {"c1", "c2"}
    assert runtime["c1"].stages["stage_1"].state == "pending"
    assert runtime["c1"].stages["stage_2"].state == "pending"


def test_plan_chunk_stage_dispatch_and_update_runtime():
    ctx = CtxWithStages()
    runtime = pc.init_chunk_stage_runtime(ctx, chunk_ids=["c1"])

    jobs = pc.plan_chunk_stage_dispatch(ctx, runtime)
    assert len(jobs) == 1
    assert jobs[0].chunk_id == "c1"
    assert jobs[0].stage_name == "extract"

    pc.update_chunk_stage_runtime(
        runtime,
        [{"chunk_id": "c1", "stage_name": "extract", "ok": True}],
    )
    jobs_after = pc.plan_chunk_stage_dispatch(ctx, runtime)
    assert len(jobs_after) == 1
    assert jobs_after[0].stage_name == "classify"


def test_execute_stage_round_success_and_failure_flow():
    ctx = CtxWithStages()
    runtime = pc.init_chunk_stage_runtime(ctx, chunk_ids=["c1", "c2"])

    def runner(job, _ctx):
        if job.chunk_id == "c1" and job.stage_name == "extract":
            return {"ok": True}
        return {"ok": False, "error": "mock-fail"}

    summary = pc.execute_stage_round(ctx, runtime, runner)
    assert summary["dispatched_jobs"] == 2
    assert summary["finished_chunks"] == 0
    assert summary["pending_jobs"] == 2

    # c1 成功進入下一階段，c2 保持 failed 可重試
    jobs_after = pc.plan_chunk_stage_dispatch(ctx, runtime)
    routed = {(j.chunk_id, j.stage_name) for j in jobs_after}
    assert ("c1", "classify") in routed
    assert ("c2", "extract") in routed


def test_run_stage_pipeline_completes_all_chunks():
    ctx = CtxWithStages()
    runtime = pc.init_chunk_stage_runtime(ctx, chunk_ids=["c1", "c2"])

    def runner(_job, _ctx):
        return {"ok": True}

    report = pc.run_stage_pipeline(ctx, runtime, runner, max_rounds=5)
    assert report["final"]["finished_chunks"] == 2
    assert report["max_rounds_reached"] is False
    # 兩個 chunk、兩個 stage，理論上 2 輪收斂
    assert report["final"]["round"] == 2


def test_run_stage_pipeline_stops_when_no_dispatchable_jobs():
    ctx = CtxWithStages()
    runtime = pc.init_chunk_stage_runtime(ctx, chunk_ids=["c1"])
    runtime["c1"].mark_started("extract")  # 模擬外部執行中，這輪不可再派工

    def runner(_job, _ctx):
        return {"ok": True}

    report = pc.run_stage_pipeline(ctx, runtime, runner, max_rounds=3)
    assert report["final"]["dispatched_jobs"] == 0
    assert report["final"]["blocked_chunks"] == 1
