import csv
import inspect
import queue
import threading
from types import SimpleNamespace

from czjLLM.job_manager.win_gui import (
    _GUIClient,
    _GuiEvents,
    _audit_reader_worker,
    _tooltip_screen_position,
    _tk_geometry_axis,
    _monitor_work_area_at,
    format_llm_audit_summary,
    format_audit_distribution_help,
    select_audit_axis_ticks,
    _fmt_audit_number,
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
    assert "Template P50/P95 52.5/67.8" in summary
    assert "Slice time P50/P95 2.0/3.8s" in summary
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
    assert 'LLM Token / Context Distribution ⓘ' in source
    assert 'audit_canvas = tk.Canvas(' in source
    assert '("elapsed_seconds", "Slice time"' in source
    assert '("template_tokens", "Template"' not in source
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
    assert "Slice time unknown" in summary
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
    assert 'entries = ("P50 unknown", "P95 unknown", "max unknown")' in source
    assert "if count:" in source



def test_audit_distribution_help_explains_histogram_semantics():
    general = format_audit_distribution_help()
    assert "不是時間序列" in general
    assert "指標值由低到高" in general
    assert "樣本數" in general
    assert "峰值正規化" in general
    assert "P50" in general and "P95" in general and "max" in general

    context = format_audit_distribution_help("context_usage_ratio")
    assert "Context %" in context
    assert "context limit" in context
    assert "100%" in context

    latency = format_audit_distribution_help("elapsed_seconds")
    assert "Slice time（切片耗時）" in latency
    assert "prompt_file" in latency
    assert "worker/queue" in latency
    assert "merge/reduction" in latency
    assert "JSON repair" in latency


def test_audit_distribution_panel_binds_hover_help_tooltip():
    from czjLLM.job_manager import win_gui

    source = inspect.getsource(win_gui._gui_proc_main)
    assert "LLM Token / Context Distribution ⓘ" in source
    assert 'audit_canvas.bind("<Motion>", _audit_canvas_help)' in source
    assert 'audit_canvas.bind("<Leave>", _hide_audit_tooltip)' in source
    assert 'audit_toggle.bind("<Enter>", _audit_header_help)' in source
    assert 'format_audit_distribution_help("template_tokens")' in source
    assert "format_audit_distribution_help(key)" in source
    assert 'audit_canvas.bind("<Configure>", _audit_canvas_resized)' in source
    assert "root.after_idle(_draw_audit_distribution)" in source
    assert "def _audit_canvas_layout_width():" in source
    assert "width = _audit_canvas_layout_width()" in source
    assert "tk.Toplevel(root)" in source



def test_audit_distribution_layout_moves_slice_time_into_template_slot():
    from czjLLM.job_manager import win_gui

    source = inspect.getsource(win_gui._gui_proc_main)
    assert '_audit_chart_keys = (' in source
    assert '"input_tokens", "output_tokens", "elapsed_seconds",' in source
    assert '"task_text_tokens", "context_usage_ratio",' in source
    assert '("elapsed_seconds", "Slice time"' in source
    assert '("template_tokens", "Template"' not in source
    assert "cols = 3 if row == 0 else 4" in source



def test_audit_header_help_reaches_template_definition():
    from czjLLM.job_manager import win_gui

    source = inspect.getsource(win_gui._gui_proc_main)
    assert 'format_audit_distribution_help("template_tokens")' in source
    assert '"template_tokens"' not in source.split("_audit_chart_keys = (", 1)[1].split(")", 1)[0]


def test_audit_canvas_redraws_after_resize_when_expanded():
    from czjLLM.job_manager import win_gui

    source = inspect.getsource(win_gui._gui_proc_main)
    assert 'def _audit_canvas_resized(_event=None):' in source
    assert 'if _audit_expanded:' in source
    assert 'root.after_idle(_draw_audit_distribution)' in source
    assert 'audit_canvas.bind("<Configure>", _audit_canvas_resized)' in source



def test_audit_summary_wraps_separately_from_toggle_title():
    from czjLLM.job_manager import win_gui

    source = inspect.getsource(win_gui._gui_proc_main)
    assert "audit_summary = ttk.Label(" in source
    assert 'audit_toggle.configure(text=f"{arrow} LLM Token / Context Distribution ⓘ")' in source
    assert "audit_summary.configure(text=format_llm_audit_summary(_audit_stats))" in source
    assert 'audit_section.bind("<Configure>", _resize_audit_summary_wrap)' in source
    assert "wraplength=max(240, int(event.width) - 16)" in source
    assert 'audit_summary.bind("<Enter>", _audit_header_help)' in source


def test_audit_hover_uses_same_effective_width_as_drawing():
    from czjLLM.job_manager import win_gui

    source = inspect.getsource(win_gui._gui_proc_main)
    assert "def _audit_canvas_layout_width():" in source
    assert source.count("width = _audit_canvas_layout_width()") >= 2
    assert "return max(640, int(audit_canvas.winfo_width() or 640))" in source



def test_audit_hover_uses_same_effective_height_as_drawing():
    from czjLLM.job_manager import win_gui

    source = inspect.getsource(win_gui._gui_proc_main)
    assert "def _audit_canvas_layout_height():" in source
    assert source.count("height = _audit_canvas_layout_height()") >= 2
    assert "return max(340, int(audit_canvas.winfo_height() or 340))" in source



def test_audit_tooltip_geometry_supports_negative_screen_coordinates():
    from czjLLM.job_manager import win_gui

    source = inspect.getsource(win_gui._gui_proc_main)
    assert "geometry_x = _tk_geometry_axis(" in source
    assert "geometry_y = _tk_geometry_axis(" in source
    assert '_audit_tooltip.geometry(f"{geometry_x}{geometry_y}")' in source
    assert 'geometry(f"{tooltip_x:+d}{tooltip_y:+d}")' not in source



def test_tooltip_screen_position_stays_within_virtual_screen():
    # Near right/bottom edge: prefer left/up so the whole tooltip remains visible.
    x, y = _tooltip_screen_position(
        1910, 1070, 520, 220, 0, 0, 1920, 1080
    )
    assert x == 1376
    assert y == 834
    assert 0 <= x <= 1920 - 520
    assert 0 <= y <= 1080 - 220

    # Virtual desktop can extend left/up of the primary display.
    x, y = _tooltip_screen_position(
        -1900, -1050, 520, 220, -1920, -1080, 3840, 2160
    )
    assert -1920 <= x <= 1920 - 520
    assert -1080 <= y <= 1080 - 220

    # Oversized tooltip clamps to the virtual-screen origin instead of escaping.
    x, y = _tooltip_screen_position(
        100, 100, 3000, 2000, -100, -50, 800, 600
    )
    assert (x, y) == (-100, -50)


def test_audit_tooltip_measures_and_clamps_before_geometry():
    from czjLLM.job_manager import win_gui

    source = inspect.getsource(win_gui._gui_proc_main)
    assert "_audit_tooltip.update_idletasks()" in source
    assert "_audit_tooltip.winfo_reqwidth()" in source
    assert "_audit_tooltip.winfo_reqheight()" in source
    assert "root.winfo_vrootx()" in source
    assert "root.winfo_vrooty()" in source
    assert "_tooltip_screen_position(" in source
    assert "_tk_geometry_axis(" in source
    assert '_audit_tooltip.geometry(f"{geometry_x}{geometry_y}")' in source



def test_tk_geometry_axis_converts_negative_absolute_position_to_far_edge_offset():
    # Tk interprets a negative wm-geometry coordinate as an offset from the
    # right/bottom edge, not as an absolute negative virtual-desktop position.
    assert _tk_geometry_axis(1376, 520, 0, 1920) == "+1376"
    assert _tk_geometry_axis(-1800, 520, -1920, 3840) == "-3200"
    assert _tk_geometry_axis(-1000, 220, -1080, 2160) == "-1860"



def test_monitor_work_area_helper_falls_back_off_windows(monkeypatch):
    from czjLLM.job_manager import win_gui

    monkeypatch.setattr(win_gui, "IS_WIN", False)
    assert _monitor_work_area_at(
        1900, 100, -1920, 0, 3840, 1080
    ) == (-1920, 0, 3840, 1080)


def test_audit_tooltip_clamps_against_pointer_monitor_not_virtual_rectangle():
    from czjLLM.job_manager import win_gui

    source = inspect.getsource(win_gui._gui_proc_main)
    assert "monitor_x, monitor_y, monitor_width, monitor_height = _monitor_work_area_at(" in source
    assert "tooltip_width," in source and "tooltip_height," in source
    assert "monitor_x," in source and "monitor_y," in source
    assert "monitor_width," in source and "monitor_height," in source
    assert "_tk_geometry_axis(" in source


def test_audit_format_keeps_full_comma_grouped_values():
    assert _fmt_audit_number(62811.5) == "62,811.5"
    assert _fmt_audit_number(82381.4) == "82,381.4"
    assert _fmt_audit_number(57597) == "57,597.0"
    assert _fmt_audit_number(12345678) == "12,345,678.0"
    # Percentile interpolation can produce a binary 67.74999999999999.
    assert _fmt_audit_number(67.74999999999999) == "67.8"
    assert _fmt_audit_number(-67.74999999999999) == "-67.8"
    assert _fmt_audit_number(2.25) == "2.3"
    stats = {"calls": 1, "component_rows": 1, "metrics": {
        "input_tokens": {"count": 1, "p50": 62811.5},
        "output_tokens": {"count": 1, "p50": 1234.5},
        "template_tokens": {"count": 1, "p50": 82381.4, "p95": 82381.4},
        "elapsed_seconds": {"count": 1, "p50": 75.4, "p95": 75.4},
        "context_usage_ratio": {"count": 1, "p50": 49.2, "p95": 49.2},
    }}
    summary = format_llm_audit_summary(stats)
    assert "62,811.5" in summary
    assert "82,381.4" in summary
    assert "1,234.5" in summary
    assert "49.2%" in summary and "75.4s" in summary
    assert "62.8k" not in summary



def test_audit_summary_uses_decimal_safe_rounding_for_context_and_slice_time():
    # Exercise the actual GUI header formatter, not just _fmt_audit_number.
    stats = {"calls": 3, "component_rows": 0, "metrics": {
        "context_usage_ratio": {"count": 3, "p50": 2.25, "p95": 67.74999999999999},
        "elapsed_seconds": {"count": 3, "p50": 2.25, "p95": 67.74999999999999},
    }}
    summary = format_llm_audit_summary(stats)
    assert "Context P50 2.3% / P95 67.8%" in summary
    assert "Slice time P50/P95 2.3/67.8s" in summary
    assert "2.2%" not in summary
    assert "2.2/" not in summary


def test_audit_summary_half_up_from_loaded_percentiles(tmp_path):
    # Two real audit rows produce the 2.25 half-up boundary in both metrics.
    audit_file = tmp_path / "rounding.csv"
    fields = ["ok", "prompt_file", "token_usage_source", "input_tokens",
              "output_tokens", "context_usage_ratio", "elapsed_seconds"]
    with audit_file.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields)
        writer.writeheader()
        writer.writerow(dict(ok="YES", prompt_file="slice-1.txt",
                             token_usage_source="llm_api_usage",
                             input_tokens="100", output_tokens="20",
                             context_usage_ratio="0.02", elapsed_seconds="2.2"))
        writer.writerow(dict(ok="YES", prompt_file="slice-2.txt",
                             token_usage_source="llm_api_usage",
                             input_tokens="100", output_tokens="20",
                             context_usage_ratio="0.025", elapsed_seconds="2.3"))
    summary = format_llm_audit_summary(load_llm_audit_distribution(str(audit_file)))
    assert "Context P50 2.3%" in summary
    assert "Slice time P50/P95 2.3/" in summary


def test_axis_key_ticks_dedupe_and_avoid_overlaps():
    constant = {"count": 4, "min": 42, "p50": 42, "p95": 42, "max": 42}
    assert len(select_audit_axis_ticks(constant, 300)) == 1
    close = {"count": 20, "min": 100, "p50": 150,
             "p95": 199, "max": 200}
    ticks = select_audit_axis_ticks(close, 180)
    assert 1 <= len(ticks) <= 4
    assert any(item["name"] == "P50" for item in ticks)
    for left, right in zip(ticks, ticks[1:]):
        assert right["x"] - left["x"] >= (left["width"] + right["width"]) / 2 + 5
    for tick in ticks:
        assert 0 <= tick["x"] - tick["width"] / 2
        assert tick["x"] + tick["width"] / 2 <= 180
    broad = {"count": 10, "min": 0, "p50": 1000,
             "p95": 8000, "max": 10000}
    wide_ticks = select_audit_axis_ticks(broad, 800)
    assert len(wide_ticks) == 4
    assert any("10,000.0" in t["label"] for t in wide_ticks)


def test_throughput_uses_api_in_plus_out_and_provider_cache_truth(tmp_path):
    p = tmp_path / "audit.csv"
    fields = ["ok", "prompt_file", "token_usage_source", "input_tokens",
              "output_tokens", "total_tokens", "processing_tps", "elapsed_seconds",
              "task_text_tokens", "template_tokens", "stage_identity",
              "model", "base_url", "task", "prompt_component_token_source",
              "cached_input_tokens", "cached_input_token_source"]
    rows = [
        dict(ok="YES", prompt_file="slice.txt", token_usage_source="llm_api_usage",
             input_tokens="100", output_tokens="20", total_tokens="999",
             processing_tps="999", elapsed_seconds="2",
             cached_input_tokens="40", cached_input_token_source="provider_usage"),
        dict(ok="YES", prompt_file="slice2.txt", token_usage_source="llm_api_usage",
             input_tokens="100", output_tokens="20", elapsed_seconds="2",
             cached_input_tokens="0", cached_input_token_source="provider_usage"),
        dict(ok="NO", prompt_file="broken.txt", token_usage_source="unavailable",
             input_tokens="0", output_tokens="0", elapsed_seconds="3"),
        dict(ok="YES", prompt_file="zero.txt", token_usage_source="llm_api_usage",
             input_tokens="100", output_tokens="20", elapsed_seconds="0"),
        dict(ok="YES", prompt_file="", token_usage_source="llm_api_usage",
             input_tokens="100", output_tokens="20", elapsed_seconds="1"),
        dict(ok="YES", prompt_file="missing.txt", token_usage_source="llm_api_usage",
             input_tokens="", output_tokens="20", elapsed_seconds="1"),
    ]
    with p.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    stats = load_llm_audit_distribution(str(p))
    assert stats["metrics"]["total_tok_per_s"]["count"] == 2
    assert stats["metrics"]["total_tok_per_s"]["p50"] == 60
    assert stats["metrics"]["effective_tok_per_s_est"]["count"] == 2
    assert stats["metrics"]["effective_tok_per_s_est"]["p50"] == 50
    assert stats["effective_provider_rows"] == 2
    assert stats["effective_heuristic_rows"] == 0


def test_heuristic_requires_stage_history_and_never_claims_api_truth(tmp_path):
    p = tmp_path / "stage.csv"
    fields = ["ok", "prompt_file", "token_usage_source", "input_tokens",
              "output_tokens", "elapsed_seconds", "task_text_tokens",
              "template_tokens", "stage_identity", "model", "base_url",
              "task", "prompt_component_token_source"]
    base = dict(ok="YES", prompt_file="slice.txt", token_usage_source="llm_api_usage",
                input_tokens="100", output_tokens="20", elapsed_seconds="2",
                task_text_tokens="70", template_tokens="30", model="m",
                base_url="endpoint", task="task", stage_identity="stage-A",
                prompt_component_token_source="local_tokenizer_no_special_tokens")
    rows = [dict(base) for _ in range(3)]
    rows += [dict(base, stage_identity="stage-B"),
             dict(base, stage_identity="", task_text_tokens="70"),
             dict(base, stage_identity="stage-C", template_tokens="30"),
             dict(base, stage_identity="stage-C", template_tokens="100"),
             dict(base, stage_identity="stage-C", template_tokens="30")]
    with p.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    stats = load_llm_audit_distribution(str(p))
    assert stats["metrics"]["total_tok_per_s"]["count"] == len(rows)
    assert stats["effective_provider_rows"] == 0
    assert stats["effective_heuristic_rows"] == 1
    assert stats["metrics"]["effective_tok_per_s_est"]["count"] == 1
    # 50% of the stable 30-token template is a possible reuse proxy.
    assert stats["metrics"]["effective_tok_per_s_est"]["p50"] == 52.5


def test_throughput_gui_layout_and_tooltips_are_explicit():
    from czjLLM.job_manager import win_gui
    source = inspect.getsource(win_gui._gui_proc_main)
    assert '"total_tok_per_s", "effective_tok_per_s_est"' in source
    assert '"total_tok_per_s", "Total tok/s"' in source
    assert '"effective_tok_per_s_est", "Effective tok/s (est.)"' in source
    assert 'cols = 3 if row == 0 else 4' in source
    assert 'select_audit_axis_ticks(snap, x1 - x0, suffix)' in source
    assert 'effective_provider_rows' in source
    assert 'effective_heuristic_rows' in source
    assert 'audit_canvas.create_text(' in source
    total_help = format_audit_distribution_help("total_tok_per_s")
    effective_help = format_audit_distribution_help("effective_tok_per_s_est")
    assert "observed request-level throughput" in total_help
    assert "不是純 GPU" in total_help
    assert "heuristic / estimated" in effective_help
    assert "provider" in effective_help and "prefix" in effective_help
