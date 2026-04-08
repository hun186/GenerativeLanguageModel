from czjLLM.job_manager import job_config as jc


class _DummyCtx:
    task = ""


def test_set_task_single_stage(monkeypatch):
    monkeypatch.setattr(
        jc,
        "taskSetting",
        {
            "TaskA": {"CT_name": "A desc"},
            "TaskB": {"CT_name": "B desc"},
        },
    )
    answers = iter(["1", "2"])  # single -> TaskB
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    ctx = _DummyCtx()
    selected = jc.set_task(ctx)

    assert selected == "TaskB"
    assert ctx.task == "TaskB"
    assert not hasattr(ctx, "stages")


def test_set_task_multi_stage(monkeypatch):
    monkeypatch.setattr(
        jc,
        "taskSetting",
        {
            "TaskA": {"CT_name": "A desc"},
            "TaskB": {"CT_name": "B desc"},
        },
    )
    # multi -> TaskA -> add -> TaskB -> source(previous) -> done
    answers = iter(["2", "1", "1", "2", "1", "2"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    ctx = _DummyCtx()
    selected = jc.set_task(ctx)

    assert selected == "TaskA"
    assert ctx.task == "TaskA"
    assert len(ctx.stages) == 2
    assert ctx.stages[0]["task_key"] == "TaskA"
    assert ctx.stages[0]["input_from"] == "original"
    assert ctx.stages[0]["persist_output"] == "always"
    assert ctx.stages[1]["task_key"] == "TaskB"
    assert ctx.stages[1]["input_from"] == "previous"
    assert ctx.stages[1]["persist_output"] == "final"


def test_set_task_multi_stage_supports_named_stage_input_source(monkeypatch):
    monkeypatch.setattr(
        jc,
        "taskSetting",
        {
            "TaskA": {"CT_name": "A desc"},
            "TaskB": {"CT_name": "B desc"},
        },
    )
    # multi -> stage1(TaskA) -> add
    # stage2(TaskB, previous) -> add
    # stage3(TaskA, stage_name -> stage_1) -> done
    answers = iter([
        "2",  # workflow=multi
        "1",  # stage1 task=TaskA
        "1",  # continue=add
        "2",  # stage2 task=TaskB
        "1",  # stage2 input_from=previous
        "1",  # continue=add
        "1",  # stage3 task=TaskA
        "3",  # stage3 input_from=stage_name
        "1",  # pick stage_1
        "2",  # continue=done
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    ctx = _DummyCtx()
    selected = jc.set_task(ctx)

    assert selected == "TaskA"
    assert len(ctx.stages) == 3
    assert ctx.stages[2]["input_from"] == "stage_1"
    assert ctx.stages[2]["persist_output"] == "final"
