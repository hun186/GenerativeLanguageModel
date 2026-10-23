import importlib.util
import sys
import threading
import types
from pathlib import Path
from types import SimpleNamespace

from czjLLM.reduction.execution_budget import ExecutionBudget


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


def test_actual_row_executor_is_capped_without_consuming_leaf_permits(monkeypatch):
    seen = []

    class RecordingExecutor:
        def __init__(self, max_workers, thread_name_prefix):
            seen.append((max_workers, thread_name_prefix))

        def shutdown(self, wait):
            assert wait is True

    monkeypatch.setattr(producer, "ThreadPoolExecutor", RecordingExecutor)
    ctx = SimpleNamespace(
        mode="sql",
        stages=[{"name": "one"}],
        sql_enable_multistage_stream=True,
        multistage_row_parallelism=8,
        n_process=8,
        _execution_budget=ExecutionBudget(2),
    )
    progress = SimpleNamespace(update=lambda *_args: None)

    assert producer.produce_rows(
        ctx, [], registry=object(), meter_fn="unused", low=0,
        stop_event=threading.Event(), consumer=None, p_sched=progress,
    ) == 0
    assert seen == [(2, "multistage-row")]
    assert ctx._execution_budget.snapshot().in_use == 0


def test_cancelled_scheduler_releases_running_marker_without_teardown(monkeypatch):
    from czjLLM.reduction.execution import ExecutionCancelled
    states = []
    monkeypatch.setattr(producer, "schedule_one_row",
                        lambda *a, **k: (_ for _ in ()).throw(ExecutionCancelled("cancelled")))
    monkeypatch.setattr(producer, "mark_not_running",
                        lambda _ctx, _pk, state: states.append(state))
    ctx = SimpleNamespace(mode="sql", stages=[{"name": "one"}],
                          sql_enable_multistage_stream=True, n_process=1)
    stop_event = threading.Event()
    progress = SimpleNamespace(update=lambda *_args: None)
    assert producer.produce_rows(ctx, [("pk", "text")], object(), "meter", 0,
                                 stop_event, None, progress) == 0
    assert states == ["cancelled"]
    assert ctx._producer_cancelled is True
    assert stop_event.is_set() is False


def test_producer_schedule_exception_emits_run_incident_without_failing_batch(
    tmp_path, monkeypatch,
):
    import json
    from czjLLM.utilities.processing_quality import quality_event_path, QualityTailReader
    released = []
    monkeypatch.setattr(producer, "schedule_one_row",
                        lambda *_a, **_kw: (_ for _ in ()).throw(
                            RuntimeError("confidential schedule exception")
                        ))
    monkeypatch.setattr(producer, "mark_not_running",
                        lambda _ctx, _pk, state: released.append(state))
    ctx = SimpleNamespace(
        mode="sql", n_process=1, stages=[{"name": "one"}],
        sql_enable_multistage_stream=True,
        llm_call_audit_path=str(tmp_path / "llm_call_audit_producer.csv"),
        llm_call_audit_run_id="producer-test",
    )
    progress = SimpleNamespace(update=lambda *_a: None)
    assert producer.produce_rows(
        ctx, [("private-document", "raw private text")],
        object(), "meter", 0, threading.Event(), None, progress,
    ) == 0
    assert released == ["schedule_error"]
    path = quality_event_path(ctx.llm_call_audit_path)
    data = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(data) == 1
    assert data[0]["code"] == "PRODUCER_SCHEDULE_EXCEPTION"
    assert data[0]["scope"] == "run" and data[0]["document_id"] == data[0]["slice_id"] == ""
    assert "private-document" not in path.read_text(encoding="utf-8")
    assert "confidential schedule exception" not in path.read_text(encoding="utf-8")
    stats = QualityTailReader(str(path)).poll()[1]
    assert stats["producer_operational_failure_events"] == 1
    assert stats["documents_decided"] == 0


def test_producer_backpressure_exception_emits_run_incident_without_dispatch(
    tmp_path, monkeypatch,
):
    import json
    from czjLLM.utilities.processing_quality import quality_event_path
    monkeypatch.setattr(producer, "producer_backpressure_wait",
                        lambda **_kw: (_ for _ in ()).throw(
                            RuntimeError("private backpressure")
                        ))
    monkeypatch.setattr(producer, "schedule_one_row",
                        lambda *_a, **_kw: (_ for _ in ()).throw(
                            AssertionError("backpressure failure must skip this row")
                        ))
    ctx = SimpleNamespace(
        mode="sql", n_process=1, stages=[{"name": "one"}],
        sql_enable_multistage_stream=True,
        llm_call_audit_path=str(tmp_path / "llm_call_audit_backpressure.csv"),
    )
    progress = SimpleNamespace(update=lambda *_a: None)
    assert producer.produce_rows(
        ctx, [("secret-pk", "text")],
        object(), "meter", 0, threading.Event(), None, progress,
    ) == 0
    path = quality_event_path(ctx.llm_call_audit_path)
    data = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [r["code"] for r in data] == ["PRODUCER_BACKPRESSURE_EXCEPTION"]
    assert "secret-pk" not in path.read_text(encoding="utf-8")
    assert "private backpressure" not in path.read_text(encoding="utf-8")


def test_producer_future_failure_is_observed_at_future_completion_boundary(
    tmp_path, monkeypatch,
):
    import json
    from concurrent.futures import Future
    from czjLLM.utilities.processing_quality import quality_event_path

    class FailedExecutor:
        def __init__(self, max_workers, thread_name_prefix):
            assert max_workers == 2 and thread_name_prefix == "multistage-row"

        def submit(self, *_args, **_kwargs):
            fut = Future()
            fut.set_exception(RuntimeError("private worker exception"))
            return fut

        def shutdown(self, wait):
            assert wait is True

    monkeypatch.setattr(producer, "ThreadPoolExecutor", FailedExecutor)
    ctx = SimpleNamespace(
        mode="sql", n_process=2, stages=[{"name": "one"}],
        sql_enable_multistage_stream=True, _execution_budget=ExecutionBudget(2),
        llm_call_audit_path=str(tmp_path / "llm_call_audit_future.csv"),
    )
    progress = SimpleNamespace(update=lambda *_a: None)
    assert producer.produce_rows(
        ctx, [("private-pk", "text")],
        object(), "meter", 0, threading.Event(), None, progress,
    ) == 0
    path = quality_event_path(ctx.llm_call_audit_path)
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1 and rows[0]["code"] == "PRODUCER_FUTURE_EXCEPTION"
    assert rows[0]["document_id"] == rows[0]["slice_id"] == ""
    assert "private worker exception" not in path.read_text(encoding="utf-8")


def test_producer_quality_audit_failure_is_best_effort(tmp_path, monkeypatch):
    released = []
    warnings = []
    monkeypatch.setattr(producer, "emit_quality_event",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(
                            OSError("audit cannot write")
                        ))
    monkeypatch.setattr(producer, "tlog_warn", warnings.append)
    monkeypatch.setattr(producer, "schedule_one_row",
                        lambda *_a, **_kw: (_ for _ in ()).throw(
                            RuntimeError("scheduler failed")
                        ))
    monkeypatch.setattr(producer, "mark_not_running",
                        lambda _ctx, _pk, state: released.append(state))
    ctx = SimpleNamespace(
        mode="sql", n_process=1, stages=[{"name": "one"}],
        sql_enable_multistage_stream=True,
        llm_call_audit_path=str(tmp_path / "llm_call_audit_unwritable.csv"),
    )
    progress = SimpleNamespace(update=lambda *_a: None)
    assert producer.produce_rows(
        ctx, [("pk", "text")], object(), "meter", 0,
        threading.Event(), None, progress,
    ) == 0
    assert released == ["schedule_error"]
    assert any("quality audit failed: OSError" in warning for warning in warnings)


def test_producer_cancel_is_not_a_quality_failure(tmp_path, monkeypatch):
    from czjLLM.reduction.execution import ExecutionCancelled
    from czjLLM.utilities.processing_quality import quality_event_path
    monkeypatch.setattr(producer, "schedule_one_row",
                        lambda *_a, **_kw: (_ for _ in ()).throw(
                            ExecutionCancelled("cancelled")
                        ))
    ctx = SimpleNamespace(
        mode="sql", n_process=1, stages=[{"name": "one"}],
        sql_enable_multistage_stream=True,
        llm_call_audit_path=str(tmp_path / "llm_call_audit_cancel.csv"),
    )
    progress = SimpleNamespace(update=lambda *_a: None)
    assert producer.produce_rows(
        ctx, [("pk", "text")], object(), "meter", 0,
        threading.Event(), None, progress,
    ) == 0
    assert ctx._producer_cancelled
    assert not quality_event_path(ctx.llm_call_audit_path).exists()


def test_pending_bookkeeping_exception_is_not_a_scheduler_incident(
    tmp_path, monkeypatch,
):
    """Failures before schedule_one_row must not mislabel the scheduler."""
    from czjLLM.utilities.processing_quality import quality_event_path

    calls = []
    releases = []

    def refuse_running(_ctx, _pk):
        raise OSError("private pending lock unavailable")

    monkeypatch.setattr(producer, "mark_running", refuse_running)
    monkeypatch.setattr(producer, "schedule_one_row",
                        lambda *_args, **_kwargs: calls.append("scheduler") or 1)
    monkeypatch.setattr(producer, "mark_not_running",
                        lambda _ctx, _pk, state: releases.append(state))
    ctx = SimpleNamespace(
        mode="sql", stages=[{"name": "one"}], n_process=1,
        sql_enable_multistage_stream=True,
        llm_call_audit_path=str(tmp_path / "llm_call_audit_bookkeeping.csv"),
    )
    progress = SimpleNamespace(update=lambda *_args: None)
    assert producer.produce_rows(
        ctx, [("private-pk", "private-content")], object(), "meter", 0,
        threading.Event(), None, progress,
    ) == 0
    assert calls == []
    assert releases == ["schedule_error"]
    assert not quality_event_path(ctx.llm_call_audit_path).exists()


def test_pre_dispatch_adjustment_error_is_not_scheduler_incident(
    tmp_path, monkeypatch,
):
    from czjLLM.utilities.processing_quality import quality_event_path
    schedule_calls = []

    def fail_before_dispatch(_ctx, event, **_kwargs):
        if event == "mark_running_before_dispatch":
            raise OSError("private adjustment store unavailable")

    monkeypatch.setattr(producer, "record_adjustment", fail_before_dispatch)
    monkeypatch.setattr(producer, "schedule_one_row",
                        lambda *_args, **_kwargs: schedule_calls.append(True) or 1)
    ctx = SimpleNamespace(
        mode="sql", stages=[{"name": "one"}], n_process=1,
        sql_enable_multistage_stream=True,
        llm_call_audit_path=str(tmp_path / "llm_call_audit_before.csv"),
    )
    progress = SimpleNamespace(update=lambda *_args: None)
    assert producer.produce_rows(
        ctx, [("private-pk", "private-content")], object(), "meter", 0,
        threading.Event(), None, progress,
    ) == 0
    assert schedule_calls == []
    assert not quality_event_path(ctx.llm_call_audit_path).exists()


def test_noop_release_bookkeeping_failure_is_not_scheduler_incident(
    tmp_path, monkeypatch,
):
    from czjLLM.utilities.processing_quality import quality_event_path
    calls = []

    def fail_noop_release(_ctx, event, **_kwargs):
        if event == "schedule_noop_release":
            raise OSError("private adjustment store unavailable")

    monkeypatch.setattr(producer, "record_adjustment", fail_noop_release)
    monkeypatch.setattr(producer, "schedule_one_row",
                        lambda *_args, **_kwargs: calls.append("scheduler") or 0)
    ctx = SimpleNamespace(
        mode="sql", stages=[{"name": "one"}], n_process=1,
        sql_enable_multistage_stream=True,
        llm_call_audit_path=str(tmp_path / "llm_call_audit_noop.csv"),
    )
    progress = SimpleNamespace(update=lambda *_args: None)
    assert producer.produce_rows(
        ctx, [("private-pk", "private-content")], object(), "meter", 0,
        threading.Event(), None, progress,
    ) == 0
    assert calls == ["scheduler"]
    assert not quality_event_path(ctx.llm_call_audit_path).exists()


def test_parallel_cancellation_survives_pending_cleanup_errors(tmp_path, monkeypatch):
    """Cleanup faults must not replace ExecutionCancelled in Future.result()."""
    from czjLLM.reduction.execution import ExecutionCancelled
    from czjLLM.utilities.processing_quality import quality_event_path

    cleanup_steps = []
    warnings = []
    def cancel_row(*_args, **_kwargs):
        raise ExecutionCancelled("cooperative stop")

    def fail_release(_ctx, _pk, state):
        cleanup_steps.append(("release", state))
        raise OSError("private pending lock path")

    def fail_adjustment(_ctx, event, **_kwargs):
        cleanup_steps.append(("adjustment", event))
        if event == "cancelled_release":
            raise RuntimeError("private adjustment log")

    monkeypatch.setattr(producer, "schedule_one_row", cancel_row)
    monkeypatch.setattr(producer, "mark_not_running", fail_release)
    monkeypatch.setattr(producer, "record_adjustment", fail_adjustment)
    monkeypatch.setattr(producer, "tlog_warn", warnings.append)
    ctx = SimpleNamespace(
        mode="sql", n_process=2, stages=[{"name": "one"}],
        sql_enable_multistage_stream=True,
        _execution_budget=ExecutionBudget(2),
        llm_call_audit_path=str(tmp_path / "llm_call_audit_cancel_cleanup.csv"),
    )
    stop = threading.Event()
    progress = SimpleNamespace(update=lambda *_args: None)
    assert producer.produce_rows(
        ctx, [("private-pk", "private prompt")],
        object(), "meter", 0, stop, None, progress,
    ) == 0
    assert ctx._producer_cancelled is True
    assert stop.is_set() is False
    assert ("release", "cancelled") in cleanup_steps
    assert ("adjustment", "cancelled_release") in cleanup_steps
    assert any("cancellation cleanup failed: OSError" in w for w in warnings)
    assert any("cancellation cleanup failed: RuntimeError" in w for w in warnings)
    assert not any("multistage row future failed" in w for w in warnings)
    assert not quality_event_path(ctx.llm_call_audit_path).exists()


def test_parallel_cancel_only_adjustment_failure_is_still_cancelled(tmp_path, monkeypatch):
    """A single cleanup failure must not convert cancellation to a future error."""
    from czjLLM.reduction.execution import ExecutionCancelled
    from czjLLM.utilities.processing_quality import quality_event_path

    states = []
    monkeypatch.setattr(
        producer, "schedule_one_row",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ExecutionCancelled("cancel")),
    )
    monkeypatch.setattr(
        producer, "mark_not_running",
        lambda _ctx, _pk, state: states.append(state),
    )

    def record(_ctx, event, **_kwargs):
        if event == "cancelled_release":
            raise OSError("private cancellation adjustment")

    monkeypatch.setattr(producer, "record_adjustment", record)
    ctx = SimpleNamespace(
        mode="sql", n_process=2, stages=[{"name": "one"}],
        sql_enable_multistage_stream=True,
        _execution_budget=ExecutionBudget(2),
        llm_call_audit_path=str(tmp_path / "llm_call_audit_cancel_adjustment.csv"),
    )
    progress = SimpleNamespace(update=lambda *_args: None)
    assert producer.produce_rows(
        ctx, [("pk", "text")], object(), "meter", 0,
        threading.Event(), None, progress,
    ) == 0
    assert states == ["cancelled"]
    assert ctx._producer_cancelled is True
    assert not quality_event_path(ctx.llm_call_audit_path).exists()
