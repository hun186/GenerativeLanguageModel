from types import SimpleNamespace

from czjLLM.prompt_pipeline.runtime_support.stage_mode import (
    explicit_stage_flow,
    stage_cfg_declares_flow,
)


def test_legacy_es_single_stage_metadata_does_not_declare_stage_flow():
    # build_es_stage_cfg() returns {} for a YAML with no stage_cfg at all, and
    # may return compatibility metadata for explicit non-flow stage_cfg values.
    # Neither case should disable the legacy consumer.
    assert stage_cfg_declares_flow({}) is False

    ctx = SimpleNamespace(stage_cfg={"enabled": False, "name": "single_stage"})

    assert stage_cfg_declares_flow(ctx.stage_cfg) is False


def test_stage_cfg_with_explicit_single_stage_declares_stage_flow():
    ctx = SimpleNamespace(
        stage_cfg={
            "enabled": True,
            "name": "es_json_multistage_langroute",
            "stages": [{"name": "extract", "task": "demo", "output_col": "result"}],
        }
    )

    assert stage_cfg_declares_flow(ctx.stage_cfg) is True


def test_legacy_sql_sqlite_table_single_task_does_not_declare_stage_flow():
    # SQL, SQLite and Excel/CSV table mode share the same stream scheduler.
    # A legacy YAML normally has only mode/task/input_col/output_col and no
    # explicit stages, so it must remain on the consumer + combined writeback path.
    for mode in ("sql", "sqlite", "table"):
        ctx = SimpleNamespace(mode=mode, task="legacy-task", stages=None, task_config={})

        assert explicit_stage_flow(ctx) == []


def test_txt_single_task_does_not_declare_stage_flow_but_task_config_stages_do():
    legacy_txt_ctx = SimpleNamespace(mode="txt", task="legacy-task", stages=None, task_config={})
    multistage_txt_ctx = SimpleNamespace(
        mode="txt",
        task="ignored-when-task-config-has-stages",
        stages=None,
        task_config={"stages": [{"name": "extract", "task": "demo"}]},
    )

    assert explicit_stage_flow(legacy_txt_ctx) == []
    assert explicit_stage_flow(multistage_txt_ctx) == [{"name": "extract", "task": "demo"}]
