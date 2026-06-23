from types import SimpleNamespace

import pytest

pytest.importorskip("colorama")
pytest.importorskip("yaml")

from czjLLM.sql_mode.runtime import producer


class _AdapterStub:
    def __init__(self, pending=True):
        self.pending = pending
        self.calls = []

    def is_row_pending(self, **kwargs):
        self.calls.append(kwargs)
        return self.pending


def test_pending_recheck_announces_activation_once(monkeypatch):
    messages = []
    monkeypatch.setattr(producer, "tlog", messages.append)

    adapter = _AdapterStub(pending=True)
    ctx = SimpleNamespace(
        _pending_adapter=adapter,
        _pending_tgt_table="target_table",
        primary_key="id",
        output_cols=["result"],
    )

    assert producer._still_pending_before_dispatch(ctx, "pk-1") is True
    assert producer._still_pending_before_dispatch(ctx, "pk-2") is True

    activation_messages = [m for m in messages if "pending recheck 啟用" in m]
    assert len(activation_messages) == 1
    assert "adapter=_AdapterStub" in activation_messages[0]
    assert adapter.calls[0]["pk_value"] == "pk-1"
    assert adapter.calls[0]["output_cols"] == ["result"]


def test_pending_recheck_debug_logs_each_state(monkeypatch):
    messages = []
    monkeypatch.setattr(producer, "tlog", messages.append)

    adapter = _AdapterStub(pending=False)
    ctx = SimpleNamespace(
        _pending_adapter=adapter,
        target_table="target_table",
        primary_key="id",
        output_col="result",
        debug_pending_recheck=True,
    )

    assert producer._still_pending_before_dispatch(ctx, "pk-1") is False

    assert any("pending recheck pk=pk-1 state=already_completed" in m for m in messages)
