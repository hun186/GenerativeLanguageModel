import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace


def _load_pending_recheck_module(monkeypatch):
    console_ui = types.ModuleType("czjLLM.job_manager.console_ui")
    console_ui.tlog = lambda _msg: None
    console_ui.tlog_warn = lambda _msg: None
    monkeypatch.setitem(sys.modules, "czjLLM.job_manager.console_ui", console_ui)

    module_path = Path(__file__).resolve().parents[3] / "czjLLM/sql_mode/runtime/pending_recheck.py"
    spec = importlib.util.spec_from_file_location("pending_recheck_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_format_completion_summary_explains_dispatch_pending_and_skips(monkeypatch):
    pending_recheck = _load_pending_recheck_module(monkeypatch)
    ctx = SimpleNamespace(
        _pending_recheck_stats={
            "checked": 243,
            "pending": 237,
            "already_completed": 6,
            "errors": 0,
        },
        _pending_recheck_finalize_stats={
            "checked": 237,
            "pending": 0,
            "already_completed": 237,
            "errors": 0,
        },
        _pending_recheck_completion_stats={
            "checked": 237,
            "pending": 0,
            "already_completed": 237,
            "errors": 0,
        },
    )

    lines = pending_recheck._format_pending_recheck_completion_summary(
        ctx,
        total_rows=482,
        scheduled_rows=237,
        done_rows=243,
    )

    rendered = "\n".join(lines)
    assert "pending recheck 最終摘要" in rendered
    assert "候選總列數：482" in rendered
    assert "仍需處理/已送出=237" in rendered
    assert "已完成跳過=6" in rendered
    assert "running 中控清理快照（可能早於最後寫回）" in rendered
    assert "寫回完成後最終重查" in rendered
    assert "派工前 pending 代表當下仍需處理，不是佇列卡住" in rendered


def test_recheck_scheduled_after_writeback_records_authoritative_state(monkeypatch):
    pending_recheck = _load_pending_recheck_module(monkeypatch)

    class Adapter:
        def is_row_pending(self, **kwargs):
            return kwargs["pk_value"] == 12

    ctx = SimpleNamespace(
        _pending_adapter=Adapter(),
        _pending_tgt_table="target",
        primary_key="id",
        output_col="result",
        _pending_recheck_scheduled_pks=(11, 12),
        _pending_recheck_announced=True,
    )

    stats = pending_recheck.recheck_scheduled_after_writeback(ctx)

    assert {key: stats[key] for key in ("checked", "pending", "already_completed", "errors")} == {
        "checked": 2, "pending": 1, "already_completed": 1, "errors": 0
    }


def test_format_completion_summary_silent_without_recheck_stats(monkeypatch):
    pending_recheck = _load_pending_recheck_module(monkeypatch)
    assert pending_recheck._format_pending_recheck_completion_summary(SimpleNamespace()) == []
