"""Headless regression for the run GUI's compact incident header and row typography.

No Tk mainloop or live LLM/SQL/ES/Queue execution is required. Actual Windows
DPI, tooltip placement and click interactions remain operator acceptance.
"""
import inspect

from czjLLM.job_manager import win_gui


def test_neutral_and_incomplete_status_are_never_called_incident_counts():
    label, color, tip = win_gui.incident_button_state({}, {}, {})
    assert label == "⚠"
    assert color == "#666666"
    assert "不代表其他來源已驗證" in tip
    label, color, tip = win_gui.incident_button_state(
        {"quality_stream_status": "unverified"}, {}, {},
    )
    assert label == "⚠ ?"
    assert color == "#b00020"
    assert "不能視為零異常" in tip
    label, color, tip = win_gui.incident_button_state(
        {"quality_stream_status": "degraded_corrupt_lines"}, {}, {},
    )
    assert label == "⚠ ?"
    assert color == "#b45309"
    assert "不完整" in tip


def test_incident_badge_counts_only_operational_events():
    quality = {
        "consumer_orchestration_failure_events": 3,
        "producer_operational_failure_events": 2,
        "documents_schema_pending": 7,
    }
    label, color, tip = win_gui.incident_button_state(
        quality, {"errors": 4},
        {"stages_failed": 1, "legacy_merges_failed": 2},
    )
    assert (label, color) == ("⚠ 5", "#b00020")
    assert "事件：5 次（非文件數）" in tip
    assert "結構異常：7 筆" in tip
    assert "Recheck 錯誤：4 次；Reduction 錯誤：3 次" in tip
    # Non-event failures get a visible dot but cannot become a made-up
    # count of "incident rows" or cross-unit sum.
    label, color, _ = win_gui.incident_button_state(
        {"documents_schema_pending": 7}, {}, {},
    )
    assert (label, color) == ("⚠ •", "#b00020")
    label, color, _ = win_gui.incident_button_state(
        {}, {"errors": 2}, {},
    )
    assert (label, color) == ("⚠ •", "#b00020")
    label, _, _ = win_gui.incident_button_state(
        {"worker_phase_failure_events": 120}, {}, {},
    )
    assert label == "⚠ 99+"


def test_review_button_shares_quality_title_row_and_keeps_popup():
    src = inspect.getsource(win_gui._gui_proc_main)
    assert 'quality_header = ttk.Frame(quality_section)' in src
    assert 'recovery_button = tk.Button(' in src
    assert 'recovery_button.pack(side="right"' in src
    assert 'quality_toggle = ttk.Button(quality_header)' in src
    assert 'quality_toggle.pack(side="left", fill="x", expand=True)' in src
    assert 'recovery_button.pack(anchor="e"' not in src
    assert src.count('recovery_button = tk.Button(') == 1
    assert 'show_recovery_review(' in src
    assert '_recovery_review_window.lift()' in src
    assert 'recovery_button.bind("<Enter>"' not in src  # multiline binding below
    assert 'recovery_button.bind(' in src and '"<Enter>"' in src
    assert 'recovery_button.bind("<Leave>", _hide_audit_tooltip)' in src
    assert '_incident_tooltip_text' in src
    assert '_refresh_incident_button()' in src


def test_quality_summary_uses_full_available_width_and_document_rows_fit_font():
    src = inspect.getsource(win_gui._gui_proc_main)
    assert 'quality_section.bind("<Configure>", _resize_quality_wrap)' in src
    assert 'quality_summary.configure(wraplength=width)' in src
    assert 'quality_codes.configure(wraplength=width)' in src
    assert 'tkfont.nametofont("TkDefaultFont").metrics("linespace")' in src
    assert 'rowheight=max(28, document_line_height + 10)' in src
    assert 'style="DocumentProgress.Treeview"' in src
    assert '"DocumentProgress.Treeview.Heading"' in src
    assert 'document_grid.bind("<<TreeviewSelect>>", _document_selected)' in src


def test_cancel_still_requests_cooperative_draining_not_forced_termination():
    src = inspect.getsource(win_gui._gui_proc_main)
    assert 'cancel_event.set()' in src
    assert 'cancel_button.configure(state="disabled")' in src
    assert 'cancel_status.configure(text="Cancellation requested")' in src
    assert 'cancel_status.configure(text="Cancelled / safely drained")' in src
    assert 'terminate(' not in src
    assert 'kill(' not in src
