import json
import os
from types import SimpleNamespace

import pytest

pytest.importorskip("colorama")
pytest.importorskip("yaml")

from czjLLM.sql_mode.runtime import pending_recheck, producer


class _AdapterStub:
    def __init__(self, pending=True):
        self.pending = pending
        self.calls = []

    def is_row_pending(self, **kwargs):
        self.calls.append(kwargs)
        return self.pending


def test_pending_recheck_announces_activation_once(monkeypatch):
    messages = []
    monkeypatch.setattr(pending_recheck, "tlog", messages.append)

    adapter = _AdapterStub(pending=True)
    ctx = SimpleNamespace(
        _pending_adapter=adapter,
        _pending_tgt_table="target_table",
        primary_key="id",
        output_cols=["result"],
    )

    assert pending_recheck.still_pending_before_dispatch(ctx, "pk-1") is True
    assert pending_recheck.still_pending_before_dispatch(ctx, "pk-2") is True

    activation_messages = [m for m in messages if "pending recheck 自動啟用" in m]
    assert len(activation_messages) == 1
    assert "adapter=_AdapterStub" in activation_messages[0]
    assert adapter.calls[0]["pk_value"] == "pk-1"
    assert adapter.calls[0]["output_cols"] == ["result"]


def test_pending_recheck_debug_logs_each_state(monkeypatch):
    messages = []
    monkeypatch.setattr(pending_recheck, "tlog", messages.append)

    adapter = _AdapterStub(pending=False)
    ctx = SimpleNamespace(
        _pending_adapter=adapter,
        target_table="target_table",
        primary_key="id",
        output_col="result",
        debug_pending_recheck=True,
    )

    assert pending_recheck.still_pending_before_dispatch(ctx, "pk-1") is False

    assert any("pending recheck pk=pk-1 state=already_completed" in m for m in messages)


class _ProgressStub:
    def update(self, _n):
        return None


class _StopEventStub:
    def is_set(self):
        return False


def test_produce_rows_announces_recheck_before_first_row(monkeypatch):
    messages = []
    monkeypatch.setattr(pending_recheck, "tlog", messages.append)
    monkeypatch.setattr(producer, "tlog", messages.append)
    monkeypatch.setattr(producer, "outstanding_now", lambda _meter_fn: 0)
    monkeypatch.setattr(producer, "meter_update", lambda *_args, **_kwargs: None)

    ctx = SimpleNamespace(
        _pending_adapter=_AdapterStub(pending=True),
        _pending_tgt_table="target_table",
        primary_key="id",
        output_cols=["result"],
    )

    scheduled = producer.produce_rows(
        ctx=ctx,
        rows_for_count=[],
        registry=None,
        meter_fn="meter.json",
        low=0,
        stop_event=_StopEventStub(),
        consumer=None,
        p_sched=_ProgressStub(),
    )

    assert scheduled == 0
    assert any("pending recheck 自動啟用" in m for m in messages)
    assert any("will iterate 0 rows；pending recheck=enabled" in m for m in messages)


def test_produce_rows_warns_and_records_when_recheck_skips_completed_row(monkeypatch, tmp_path):
    warnings = []
    progress_updates = []
    monkeypatch.setattr(producer, "tlog", lambda _msg: None)
    monkeypatch.setattr(producer, "tlog_warn", warnings.append)
    monkeypatch.setattr(producer, "outstanding_now", lambda _meter_fn: 0)
    monkeypatch.setattr(producer, "producer_backpressure_wait", lambda **_kwargs: None)
    monkeypatch.setattr(
        producer,
        "schedule_one_row",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not dispatch")),
    )

    def _capture_meter(_meter_fn, updater):
        data = {}
        updater(data)
        progress_updates.append(data["progress"])

    monkeypatch.setattr(producer, "meter_update", _capture_meter)

    skip_log = tmp_path / "pending_recheck_skips.log"
    ctx = SimpleNamespace(
        _pending_adapter=_AdapterStub(pending=False),
        _pending_tgt_table="target_table",
        primary_key="id",
        output_cols=["result"],
        sql_config_file="/configs/task_a.json",
        pending_recheck_skip_log_path=str(skip_log),
    )

    scheduled = producer.produce_rows(
        ctx=ctx,
        rows_for_count=[("pk-1", "text")],
        registry=None,
        meter_fn="meter.json",
        low=0,
        stop_event=_StopEventStub(),
        consumer=None,
        p_sched=_ProgressStub(),
        p_done=_ProgressStub(),
    )

    assert scheduled == 0
    assert any("pending recheck 命中：pk=pk-1" in m for m in warnings)
    assert any("略過本次切片/派工以節省算力" in m for m in warnings)
    assert any(
        update.get("last_skip_reason") == "already_completed" and update.get("last_skip_pk") == "pk-1"
        for update in progress_updates
    )
    rows = [json.loads(line) for line in skip_log.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["pid"] == os.getpid()
    assert rows[0]["ts"]
    assert "timezone" in rows[0]
    assert rows[0]["task_json"] == "task_a.json"
    assert rows[0]["pk"] == "pk-1"
    assert rows[0]["reason"] == "already_completed"


def test_block_shuffle_preserves_outer_block_order_and_shuffles_inside_blocks():
    rows = [(f"pk-{i}", f"text-{i}") for i in range(10)]
    ctx = SimpleNamespace(
        pending_recheck_shuffle_block_size=4,
        pending_recheck_shuffle_seed=7,
    )

    shuffled = producer._maybe_block_shuffle_rows(ctx, rows)

    assert set(shuffled[:4]) == set(rows[:4])
    assert set(shuffled[4:8]) == set(rows[4:8])
    assert set(shuffled[8:]) == set(rows[8:])
    assert shuffled != rows


def test_produce_rows_uses_block_shuffle_before_dispatch(monkeypatch):
    dispatched = []
    monkeypatch.setattr(producer, "tlog", lambda _msg: None)
    monkeypatch.setattr(producer, "outstanding_now", lambda _meter_fn: 0)
    monkeypatch.setattr(producer, "producer_backpressure_wait", lambda **_kwargs: None)
    monkeypatch.setattr(producer, "still_pending_before_dispatch", lambda _ctx, _pk: True)
    monkeypatch.setattr(producer, "meter_update", lambda *_args, **_kwargs: None)

    def _record_schedule(_ctx, _registry, _meter_fn, _idx, pk, _text, source_inputs=None):
        dispatched.append(pk)

    monkeypatch.setattr(producer, "schedule_one_row", _record_schedule)

    rows = [(f"pk-{i}", f"text-{i}") for i in range(8)]
    ctx = SimpleNamespace(
        pending_recheck_shuffle_block_size=4,
        pending_recheck_shuffle_seed=7,
    )

    scheduled = producer.produce_rows(
        ctx=ctx,
        rows_for_count=rows,
        registry=None,
        meter_fn="meter.json",
        low=0,
        stop_event=_StopEventStub(),
        consumer=None,
        p_sched=_ProgressStub(),
    )

    assert scheduled == len(rows)
    assert set(dispatched[:4]) == {f"pk-{i}" for i in range(4)}
    assert set(dispatched[4:]) == {f"pk-{i}" for i in range(4, 8)}
    assert dispatched != [f"pk-{i}" for i in range(8)]


def test_pending_skip_log_trims_to_half_when_over_limit(tmp_path):
    log_path = tmp_path / "pending_recheck_skips.log"
    log_path.write_text("old-1\n" + ("x" * 1400) + "\nold-2\n", encoding="utf-8")
    ctx = SimpleNamespace(
        pending_recheck_skip_log_path=str(log_path),
        pending_recheck_skip_log_max_bytes=1024,
        sql_config_file="task_b.json",
    )

    pending_recheck.record_pending_skip(ctx, "pk-2")

    data = log_path.read_bytes()
    assert len(data) <= 1024
    assert b"old-1" not in data
    assert b'"pk": "pk-2"' in data
    assert b'"task_json": "task_b.json"' in data
