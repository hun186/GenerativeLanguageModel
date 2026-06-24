import json
from types import SimpleNamespace

from czjLLM.prompt_pipeline import pending_central


def test_order_rows_avoids_running_until_after_cold_rows(tmp_path):
    ctx = SimpleNamespace(
        PGMSubDir=str(tmp_path),
        _pending_tgt_table="target",
        pending_running_console_enabled=True,
    )

    pending_central.mark_running(ctx, "pk-1")

    rows = [("pk-1", "hot"), ("pk-2", "cold"), ("pk-3", "cold")]

    assert pending_central.order_rows_avoiding_running(ctx, rows) == [
        ("pk-2", "cold"),
        ("pk-3", "cold"),
        ("pk-1", "hot"),
    ]


def test_mark_not_running_removes_running_state(tmp_path):
    ctx = SimpleNamespace(
        PGMSubDir=str(tmp_path),
        _pending_tgt_table="target",
        pending_running_console_enabled=True,
    )

    pending_central.mark_running(ctx, "pk-1")
    assert pending_central.is_running(ctx, "pk-1") is True

    pending_central.mark_not_running(ctx, "pk-1")

    assert pending_central.is_running(ctx, "pk-1") is False


def test_order_rows_records_adjustment_log(tmp_path):
    ctx = SimpleNamespace(
        PGMSubDir=str(tmp_path),
        _pending_tgt_table="target",
        pending_running_console_enabled=True,
    )

    pending_central.mark_running(ctx, "pk-1")
    pending_central.order_rows_avoiding_running(ctx, [("pk-1", "hot"), ("pk-2", "cold")])

    log_path = tmp_path / "logs" / "pending_running_console_adjustments.log"
    assert log_path.exists()
    assert '"event": "initial_reorder"' in log_path.read_text(encoding="utf-8")


def test_adjustment_log_uses_local_iso_timestamp(tmp_path):
    ctx = SimpleNamespace(
        PGMSubDir=str(tmp_path),
        _pending_tgt_table="target",
        pending_running_console_enabled=True,
    )

    pending_central.record_adjustment(ctx, "unit_test_event", pk="pk-1")

    log_path = tmp_path / "logs" / "pending_running_console_adjustments.log"
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["event"] == "unit_test_event"
    assert isinstance(rows[0]["ts"], str)
    assert "T" in rows[0]["ts"]
    assert "timezone" in rows[0]


def test_running_console_prunes_dead_pid(tmp_path, monkeypatch):
    ctx = SimpleNamespace(
        PGMSubDir=str(tmp_path),
        _pending_tgt_table="target",
        pending_running_console_enabled=True,
    )
    console_path = tmp_path / "logs" / "pending_running_console.json"
    console_path.parent.mkdir(parents=True, exist_ok=True)
    console_path.write_text(json.dumps({
        "version": 1,
        "running": {
            "target|pk-dead": {
                "state": "running",
                "pk": "pk-dead",
                "target": "target",
                "pid": 999999,
                "started_ts": 9999999999,
                "updated_ts": 9999999999,
            }
        },
    }), encoding="utf-8")

    def _fake_kill(pid, sig):
        raise ProcessLookupError()

    monkeypatch.setattr(pending_central.os, "kill", _fake_kill)

    assert pending_central.is_running(ctx, "pk-dead") is False
    data = json.loads(console_path.read_text(encoding="utf-8"))
    assert data["running"] == {}
