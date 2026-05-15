import pytest

from czjLLM.prompt_pipeline.stage_runtime import (
    ChunkStageRuntime,
    StageDispatchJob,
    StageDefinition,
    apply_dispatch_results,
    build_dispatch_jobs,
    build_chunk_stage_runtime,
    is_chunk_finished,
    normalize_stages,
    resolve_stage_input,
    resolve_stage_task,
    should_persist_output,
    summarize_runtime,
)


def test_normalize_stages_accepts_legacy_single_task():
    stages = normalize_stages("抽取實體")
    assert len(stages) == 1
    assert stages[0] == StageDefinition(name="stage_1", task="抽取實體")


def test_normalize_stages_accepts_multistage_dict():
    stages = normalize_stages(
        {
            "stages": [
                {"name": "extract", "task": "抽取"},
                {"name": "classify", "task": "分類"},
            ]
        }
    )
    assert [s.name for s in stages] == ["extract", "classify"]
    assert [s.task for s in stages] == ["抽取", "分類"]


def test_normalize_stages_rejects_empty_stages():
    with pytest.raises(ValueError):
        normalize_stages({"stages": []})


def test_normalize_stages_rejects_duplicate_stage_names():
    with pytest.raises(ValueError, match="stage name 不可重複"):
        normalize_stages(
            {
                "stages": [
                    {"name": "route", "prompt": "分類"},
                    {"name": "route", "prompt": "抽取"},
                ]
            }
        )


def test_build_chunk_stage_runtime_initializes_pending_matrix():
    stages = [StageDefinition(name="extract", task="抽取"), StageDefinition(name="classify", task="分類")]
    runtime = build_chunk_stage_runtime(["c1", "c2"], stages)

    assert set(runtime.keys()) == {"c1", "c2"}
    assert runtime["c1"].stages["extract"].state == "pending"
    assert runtime["c1"].stages["classify"].state == "pending"


def test_chunk_runtime_state_transitions_and_next_runnable():
    runtime = ChunkStageRuntime(chunk_id="c1")
    stage_order = ["extract", "classify"]

    assert runtime.next_runnable_stage(stage_order) == "extract"

    runtime.mark_started("extract")
    assert runtime.stages["extract"].state == "running"
    assert runtime.stages["extract"].attempts == 1
    assert runtime.next_runnable_stage(stage_order) is None

    runtime.mark_success("extract")
    assert runtime.next_runnable_stage(stage_order) == "classify"

    runtime.mark_started("classify")
    runtime.mark_failed("classify", "timeout")
    assert runtime.stages["classify"].state == "failed"
    assert runtime.stages["classify"].last_error == "timeout"
    assert runtime.next_runnable_stage(stage_order) == "classify"


def test_build_dispatch_jobs_only_emits_one_job_per_chunk_and_in_order():
    stages = [StageDefinition(name="extract", task="抽取"), StageDefinition(name="classify", task="分類")]
    runtime = build_chunk_stage_runtime(["c2", "c1"], stages)

    # c1 的 extract 已完成，所以應派 classify；c2 應派 extract
    runtime["c1"].mark_success("extract")
    jobs = build_dispatch_jobs(runtime, stages)

    assert jobs == [
        StageDispatchJob(chunk_id="c1", stage_name="classify", stage_task="分類"),
        StageDispatchJob(chunk_id="c2", stage_name="extract", stage_task="抽取"),
    ]


def test_apply_dispatch_results_updates_success_and_failure():
    stages = [StageDefinition(name="extract", task="抽取"), StageDefinition(name="classify", task="分類")]
    runtime = build_chunk_stage_runtime(["c1"], stages)

    apply_dispatch_results(
        runtime,
        [
            {"chunk_id": "c1", "stage_name": "extract", "ok": True},
            {"chunk_id": "c1", "stage_name": "classify", "ok": False, "error": "timeout"},
        ],
    )

    assert runtime["c1"].stages["extract"].state == "success"
    assert runtime["c1"].stages["classify"].state == "failed"
    assert runtime["c1"].stages["classify"].last_error == "timeout"


def test_is_chunk_finished_and_summarize_runtime():
    stages = [StageDefinition(name="extract", task="抽取"), StageDefinition(name="classify", task="分類")]
    stage_order = [s.name for s in stages]
    runtime = build_chunk_stage_runtime(["c1", "c2"], stages)

    runtime["c1"].mark_success("extract")
    runtime["c1"].mark_success("classify")
    runtime["c2"].mark_started("extract")

    assert is_chunk_finished(runtime["c1"], stage_order) is True
    assert is_chunk_finished(runtime["c2"], stage_order) is False

    summary = summarize_runtime(runtime, stage_order)
    assert summary == {
        "finished_chunks": 1,
        "blocked_chunks": 1,
        "pending_jobs": 0,
    }


def test_resolve_stage_input_supports_original_previous_and_named_stage():
    stages = [
        StageDefinition(name="translate", task="翻譯", input_from="original"),
        StageDefinition(name="summarize", task="摘要", input_from="previous"),
        StageDefinition(name="route", task="分類", input_from="original"),
        StageDefinition(name="apply_tpl", task="套模板", input_from="route"),
    ]
    order = [s.name for s in stages]
    outputs = {"translate": "中文內容", "route": "A類"}

    assert resolve_stage_input(stages[0], order, outputs, "EN text") == "EN text"
    assert resolve_stage_input(stages[1], order, outputs, "EN text") == "中文內容"
    assert resolve_stage_input(stages[3], order, outputs, "EN text") == "A類"


def test_should_persist_output_policy():
    s_final = StageDefinition(name="s2", task="x", persist_output="final")
    s_always = StageDefinition(name="s1", task="x", persist_output="always")
    s_never = StageDefinition(name="s1", task="x", persist_output="never")

    assert should_persist_output(s_final, last_stage_name="s2") is True
    assert should_persist_output(s_final, last_stage_name="s3") is False
    assert should_persist_output(s_always, last_stage_name="s2") is True
    assert should_persist_output(s_never, last_stage_name="s2") is False


def test_resolve_stage_task_task_key_mode_preserves_tasksetting_mapping():
    stage = StageDefinition(
        name="extract",
        task="fallback",
        route_by="route",
        route_map={"org": "模板A"},
        route_value_mode="task_key",
    )
    outputs = {"route": "org"}
    task_setting = {"模板A": {"CT_name": "模板A", "template": lambda content: f"A:{content}"}}
    task, err = resolve_stage_task(stage, outputs, task_setting=task_setting)
    assert err is None
    assert isinstance(task, dict)
    assert callable(task["template"])


def test_resolve_stage_task_tasksetting_marker_falls_back_to_global_tasksetting(monkeypatch):
    import sys
    import types

    key = "UnitTest-Multidim-Task"
    spec = {"CT_name": key, "template": lambda content: f"MULTIDIM:{content}"}
    fake_task_config = types.ModuleType("czjLLM.taskConfig")
    fake_task_config.taskSetting = {key: spec}
    monkeypatch.setitem(sys.modules, "czjLLM.taskConfig", fake_task_config)
    stage = StageDefinition(
        name="extract",
        task="fallback",
        route_by="route",
        route_map={"zh": {"task": f"@taskSetting:{key}", "input_from": "original"}},
        route_value_mode="task",
    )

    task, err = resolve_stage_task(stage, {"route": "zh"}, task_setting=None)

    assert err is None
    assert task is spec
