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
