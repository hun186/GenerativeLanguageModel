from dataclasses import dataclass, field

from czjLLM.prompt_pipeline import stage_orchestrator as so


@dataclass
class Ctx:
    stages: list[dict[str, str]] = field(
        default_factory=lambda: [
            {"name": "extract", "task": "抽取"},
            {"name": "classify", "task": "分類"},
        ]
    )


def test_execute_stage_round_returns_typed_result():
    ctx = Ctx()
    runtime = so.init_chunk_stage_runtime(ctx, ["c1"])

    def runner(_job, _ctx):
        return {"ok": True}

    result = so.execute_stage_round(ctx, runtime, runner)
    assert result.dispatched_jobs == 1
    assert result.finished_chunks == 0
    assert result.pending_jobs == 1


def test_run_stage_pipeline_report_shape():
    ctx = Ctx(
        stages=[
            {"name": "extract", "task": "抽取", "input_from": "original", "persist_output": "never"},
            {"name": "classify", "task": "分類", "input_from": "previous", "persist_output": "always"},
        ]
    )
    runtime = so.init_chunk_stage_runtime(ctx, ["c1"])
    seen_inputs = []

    def runner(job, _ctx, input_text):
        seen_inputs.append((job.stage_name, input_text))
        if job.stage_name == "extract":
            return {"ok": True, "output": "抽取結果"}
        return {"ok": True, "output": f"分類:{input_text}"}

    report = so.run_stage_pipeline(
        ctx,
        runtime,
        runner,
        max_rounds=5,
        original_inputs={"c1": "原文甲"},
    )
    assert "rounds" in report and "final" in report
    assert report["final"]["finished_chunks"] == 1
    assert report["max_rounds_reached"] is False
    assert seen_inputs == [("extract", "原文甲"), ("classify", "抽取結果")]
    assert report["persisted_outputs"]["c1"]["classify"] == "分類:抽取結果"


def test_router_workflow_can_route_task_and_retry_source_on_route_miss():
    ctx = Ctx(
        stages=[
            {"name": "route", "task": "分類", "persist_output": "always"},
            {
                "name": "apply_template",
                "task": "fallback",
                "route_by": "route",
                "route_map": {"A": "套用A模板", "B": "套用B模板"},
                "route_value_mode": "task",
                "retry_source_on_route_miss": True,
                "max_attempts": 2,
            },
        ]
    )
    runtime = so.init_chunk_stage_runtime(ctx, ["c1"])
    route_outputs = iter(["X", "A"])  # 第一次分類異常，第二次回到可路由值
    called_tasks = []

    def runner(job, _ctx, _input_text):
        called_tasks.append(job.stage_task)
        if job.stage_name == "route":
            return {"ok": True, "output": next(route_outputs)}
        return {"ok": True, "output": "完成"}

    report = so.run_stage_pipeline(ctx, runtime, runner, max_rounds=5, original_inputs={"c1": "原文"})

    # 會先跑 route -> apply_template(路由失敗) -> route(重跑) -> apply_template(成功)
    assert called_tasks == ["分類", "分類", "套用A模板"]
    assert report["final"]["finished_chunks"] == 1


def test_router_workflow_accepts_route_output_with_punctuation_and_case():
    ctx = Ctx(
        stages=[
            {"name": "route", "task": "分類", "persist_output": "always"},
            {
                "name": "apply_template",
                "task": "fallback",
                "route_by": "route",
                "route_map": {"org": "套用ORG模板", "other": "套用OTHER模板"},
                "route_value_mode": "task",
                "retry_source_on_route_miss": True,
                "max_attempts": 2,
            },
        ]
    )
    runtime = so.init_chunk_stage_runtime(ctx, ["c1"])
    called_tasks = []

    def runner(job, _ctx, _input_text):
        called_tasks.append(job.stage_task)
        if job.stage_name == "route":
            return {"ok": True, "output": "ORG。 這是一段補充"}
        return {"ok": True, "output": "完成"}

    report = so.run_stage_pipeline(ctx, runtime, runner, max_rounds=4, original_inputs={"c1": "原文"})
    assert called_tasks == ["分類", "套用ORG模板"]
    assert report["final"]["finished_chunks"] == 1


def test_router_route_map_can_use_tasksetting_key_by_default():
    @dataclass
    class CtxRouteWithTaskSetting:
        stages: list[dict] = field(
            default_factory=lambda: [
                {"name": "route", "task": "分類"},
                {
                    "name": "apply",
                    "task": "fallback",
                    "route_by": "route",
                    "route_map": {"A": "模板A", "B": "模板B"},  # value 會被當 taskSetting key
                },
            ]
        )
        taskSetting: dict = field(default_factory=lambda: {"模板A": "實際A任務", "模板B": "實際B任務"})

    ctx = CtxRouteWithTaskSetting()
    runtime = so.init_chunk_stage_runtime(ctx, ["c1"])
    called_tasks = []

    def runner(job, _ctx, _input_text):
        called_tasks.append(job.stage_task)
        if job.stage_name == "route":
            return {"ok": True, "output": "A"}
        return {"ok": True, "output": "done"}

    report = so.run_stage_pipeline(ctx, runtime, runner, max_rounds=5, original_inputs={"c1": "原文"})
    assert called_tasks == ["分類", "實際A任務"]
    assert report["final"]["finished_chunks"] == 1


def test_stage_failure_hits_max_attempts_and_becomes_error():
    ctx = Ctx(stages=[{"name": "only", "task": "任務", "max_attempts": 1}])
    runtime = so.init_chunk_stage_runtime(ctx, ["c1"])

    def runner(_job, _ctx, _input_text):
        return {"ok": False, "error": "bad-output"}

    report = so.run_stage_pipeline(ctx, runtime, runner, max_rounds=3, original_inputs={"c1": "原文"})
    assert report["final"]["dispatched_jobs"] == 0
    assert runtime["c1"].stages["only"].state == "error"


def test_resolve_pipeline_stages_can_bind_tasksetting_keys():
    @dataclass
    class CtxTaskSetting:
        stages: list[dict] = field(
            default_factory=lambda: [
                {"name": "分類判定", "task_key": "分類判定"},
                {"name": "模板套用", "task": "@taskSetting:模板套用"},
                {"name": "直接同名"},
            ]
        )
        taskSetting: dict = field(
            default_factory=lambda: {
                "分類判定": "請輸出A/B/C",
                "模板套用": "請依分類套模板",
                "直接同名": "同名對映任務",
            }
        )

    stages = so.resolve_pipeline_stages(CtxTaskSetting())
    assert [s.task for s in stages] == ["請輸出A/B/C", "請依分類套模板", "同名對映任務"]
