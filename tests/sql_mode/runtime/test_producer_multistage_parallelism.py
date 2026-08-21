import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace


def _stub_module(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def _load_producer_module():
    stub_names = [
        "czjLLM.job_manager.console_ui",
        "czjLLM.prompt_pipeline.pipeline_controller",
        "czjLLM.prompt_pipeline.runtime_support.stage_mode",
        "czjLLM.sql_mode.runtime.workers",
        "czjLLM.sql_mode.runtime.scheduler",
        "czjLLM.sql_mode.runtime.pending_recheck",
        "czjLLM.prompt_pipeline.pending_central",
    ]
    previous_modules = {name: sys.modules.get(name) for name in stub_names}
    _stub_module("czjLLM.job_manager.console_ui", tlog=lambda *_args, **_kwargs: None, tlog_warn=lambda *_args, **_kwargs: None)
    _stub_module(
        "czjLLM.prompt_pipeline.pipeline_controller",
        producer_backpressure_wait=lambda **_kwargs: None,
        meter_update=lambda *_args, **_kwargs: None,
    )
    _stub_module("czjLLM.prompt_pipeline.runtime_support.stage_mode", explicit_stage_flow=lambda ctx: getattr(ctx, "stages", []))
    _stub_module("czjLLM.sql_mode.runtime.workers", outstanding_now=lambda _meter_fn: 0)
    _stub_module("czjLLM.sql_mode.runtime.scheduler", schedule_one_row=lambda *_args, **_kwargs: 1)
    _stub_module(
        "czjLLM.sql_mode.runtime.pending_recheck",
        announce_pending_recheck_if_enabled=lambda _ctx: False,
        pending_recheck_stats=lambda _ctx: {},
        record_pending_skip=lambda *_args, **_kwargs: None,
        still_pending_before_dispatch=lambda *_args, **_kwargs: True,
        still_pending_for_running_finalize=lambda *_args, **_kwargs: True,
    )
    _stub_module(
        "czjLLM.prompt_pipeline.pending_central",
        finalize_scheduled=lambda *_args, **_kwargs: None,
        is_running=lambda *_args, **_kwargs: False,
        mark_not_running=lambda *_args, **_kwargs: None,
        mark_running=lambda *_args, **_kwargs: None,
        order_rows_avoiding_running=lambda _ctx, rows: list(rows),
        record_adjustment=lambda *_args, **_kwargs: None,
    )

    path = Path(__file__).resolve().parents[3] / "czjLLM" / "sql_mode" / "runtime" / "producer.py"
    spec = importlib.util.spec_from_file_location("czjLLM.sql_mode.runtime.producer_isolated", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    try:
        spec.loader.exec_module(module)
    finally:
        for name, previous in previous_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
    return module


producer = _load_producer_module()


def test_multistage_parallelism_defaults_to_endpoint_pool_budget_without_n_process():
    ctx = SimpleNamespace(
        n_process=0,
        on_premises=True,
        model_spec={"base_url": ["http://llm-a/v1", "http://llm-b/v1"]},
    )

    assert producer._multistage_row_parallelism(ctx) == 4


def test_multistage_parallelism_reuses_n_process_before_endpoint_fallback():
    ctx = SimpleNamespace(
        n_process=5,
        on_premises=True,
        model_spec={"base_url": ["http://llm-a/v1", "http://llm-b/v1"]},
    )

    assert producer._multistage_row_parallelism(ctx) == 5


def test_multistage_parallelism_prefers_explicit_override():
    ctx = SimpleNamespace(
        n_process=4,
        on_premises=True,
        model_spec={"base_url": ["http://llm-a/v1", "http://llm-b/v1"]},
        stream_multistage_row_parallelism=3,
    )

    assert producer._multistage_row_parallelism(ctx) == 3
