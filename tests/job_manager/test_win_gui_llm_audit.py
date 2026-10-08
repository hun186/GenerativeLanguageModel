import csv
import inspect
import queue
import threading
from types import SimpleNamespace

from czjLLM.job_manager.win_gui import (
    _GUIClient,
    _GuiEvents,
    _audit_reader_worker,
    format_llm_audit_summary,
    load_llm_audit_distribution,
)


def _write_audit(path):
    fields = [
        "ok", "prompt_file", "token_usage_source", "input_tokens", "output_tokens", "template_tokens",
        "task_text_tokens", "context_usage_ratio", "elapsed_seconds",
    ]
    rows = [
        {"ok": "YES", "prompt_file": "slice-0.txt", "token_usage_source": "llm_api_usage", "input_tokens": "100", "output_tokens": "20",
         "template_tokens": "30", "task_text_tokens": "70", "context_usage_ratio": "0.25", "elapsed_seconds": "1.0"},
        {"ok": "YES", "prompt_file": "slice-1.txt", "token_usage_source": "llm_api_usage", "input_tokens": "200", "output_tokens": "40",
         "template_tokens": "50", "task_text_tokens": "150", "context_usage_ratio": "0.50", "elapsed_seconds": "2.0"},
        {"ok": "NO", "prompt_file": "slice-err.txt", "token_usage_source": "unavailable", "input_tokens": "0", "output_tokens": "",
         "template_tokens": "55", "task_text_tokens": "145", "context_usage_ratio": "0.0", "elapsed_seconds": ""},
        {"ok": "YES", "prompt_file": "slice-2.txt", "token_usage_source": "llm_api_usage", "input_tokens": "300", "output_tokens": "60",
         "template_tokens": "70", "task_text_tokens": "230", "context_usage_ratio": "0.75", "elapsed_seconds": "4.0"},
        {"ok": "YES", "prompt_file": "", "token_usage_source": "unavailable", "input_tokens": "",
         "output_tokens": "", "template_tokens": "", "task_text_tokens": "",
         "context_usage_ratio": "", "elapsed_seconds": "9.0"},
    ]
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_llm_audit_distribution_uses_api_usage_and_prompt_components(tmp_path):
    path = tmp_path / "audit.csv"
    _write_audit(path)

    stats = load_llm_audit_distribution(str(path))
    assert stats["calls"] == 5
    assert stats["failures"] == 1
    assert stats["component_rows"] == 4
    assert stats["metrics"]["input_tokens"]["p50"] == 200
    assert stats["metrics"]["output_tokens"]["p95"] == 58
    assert stats["metrics"]["template_tokens"]["p50"] == 52.5
    assert stats["metrics"]["task_text_tokens"]["p50"] == 147.5
    assert stats["metrics"]["context_usage_ratio"]["p50"] == 50
    assert stats["metrics"]["elapsed_seconds"]["p50"] == 2
    assert stats["metrics"]["elapsed_seconds"]["p95"] == 3.8

    summary = format_llm_audit_summary(stats)
    assert "Calls 5" in summary
    assert "Context P50 50.0% / P95 72.5%" in summary
    assert "Latency P50/P95 2.0/3.8s" in summary
    assert "Components 4/5" in summary


def test_gui_client_sends_detached_audit_path_event():
    events = queue.Queue()
    client = _GUIClient(events, SimpleNamespace(is_alive=lambda: False))
    client.set_audit_path("logs/llm_call_audit/run.csv")
    assert events.get_nowait() == (
        _GuiEvents.AUDIT_PATH,
        "logs/llm_call_audit/run.csv",
    )


def test_audit_distribution_panel_is_collapsed_by_default_and_draws_curves():
    from czjLLM.job_manager import win_gui

    source = inspect.getsource(win_gui._gui_proc_main)
    assert 'audit_section = ttk.Frame(frm)' in source
    assert 'audit_toggle = ttk.Button(audit_section)' in source
    assert 'audit_frame.pack_forget()' in source
    assert 'LLM Token / Context Distribution —' in source
    assert 'audit_canvas = tk.Canvas(' in source
    assert '("elapsed_seconds", "Slice latency"' in source
    assert 'audit_canvas.create_line(*points' in source
    assert 'elif evt == _GuiEvents.AUDIT_PATH:' in source
    assert 'target=_audit_reader_worker' in source
    assert '_audit_result_queue.get_nowait()' in source
    assert 'load_llm_audit_distribution(_audit_path)' not in source


def test_runtime_ui_connects_current_run_audit_path_to_gui():
    from czjLLM.sql_mode.runtime import runtime_ui

    source = inspect.getsource(runtime_ui.prepare_ui)
    assert 'gui.set_audit_path(getattr(ctx, "llm_call_audit_path", "") or "")' in source



def test_llm_audit_summary_shows_unknown_without_api_usage(tmp_path):
    path = tmp_path / "audit-no-usage.csv"
    fields = [
        "ok", "prompt_file", "token_usage_source", "input_tokens", "output_tokens",
        "template_tokens", "task_text_tokens", "context_usage_ratio", "elapsed_seconds",
    ]
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields)
        writer.writeheader()
        writer.writerow({
            "ok": "NO",
            "prompt_file": "slice-err.txt",
            "token_usage_source": "unavailable",
            "input_tokens": "0",
            "output_tokens": "0",
            "template_tokens": "42",
            "task_text_tokens": "128",
            "context_usage_ratio": "0",
            "elapsed_seconds": "",
        })

    summary = format_llm_audit_summary(load_llm_audit_distribution(str(path)))
    assert "In unknown" in summary
    assert "Out unknown" in summary
    assert "Context unknown" in summary
    assert "Latency unknown" in summary
    assert "In P50 0" not in summary
    assert "Out P50 0" not in summary



def test_audit_reader_parses_off_caller_thread(tmp_path, monkeypatch):
    from czjLLM.job_manager import win_gui

    audit_path = tmp_path / "audit.csv"
    audit_path.write_text("ok\nYES\n", encoding="utf-8")
    path_queue = queue.Queue()
    result_queue = queue.Queue(maxsize=1)
    stop_event = threading.Event()
    seen_threads = []

    def fake_loader(path):
        seen_threads.append(threading.current_thread().name)
        return {"calls": 1, "failures": 0, "component_rows": 0, "metrics": {}}

    monkeypatch.setattr(win_gui, "load_llm_audit_distribution", fake_loader)
    path_queue.put(str(audit_path))
    worker = threading.Thread(
        target=_audit_reader_worker,
        args=(path_queue, result_queue, stop_event, 0.05),
        name="audit-test-reader",
        daemon=True,
    )
    worker.start()
    try:
        result = result_queue.get(timeout=2.0)
        assert result["calls"] == 1
        assert seen_threads == ["audit-test-reader"]
        assert seen_threads[0] != threading.current_thread().name
    finally:
        stop_event.set()
        worker.join(timeout=1.0)



def test_expanded_audit_chart_renders_empty_percentiles_as_unknown():
    from czjLLM.job_manager import win_gui

    source = inspect.getsource(win_gui._gui_proc_main)
    assert 'else "P50 unknown   P95 unknown   max unknown"' in source
    assert "if count > 0" in source
