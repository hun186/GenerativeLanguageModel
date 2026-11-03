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



def test_document_columns_fit_actual_viewport_without_pixel_overhang():
    from czjLLM.job_manager.win_gui import fit_document_column_widths
    minimums = (205, 115, 182, 270, 55, 55, 91)
    for viewport in (985, 986, 1065, 1200, 1498, 1894, 2560):
        widths, scroll = fit_document_column_widths(viewport, minimums)
        assert not scroll
        assert sum(widths) + 12 <= viewport
        assert all(width >= minimum for width, minimum in zip(widths, minimums))
        assert widths[4:] == minimums[4:]  # counters / timestamp stay stable
        assert widths[3] >= widths[1]  # prioritize endpoint evidence
    widths, scroll = fit_document_column_widths(985, minimums)
    assert not scroll and sum(widths) + 12 == 985


def test_document_columns_scroll_only_when_viewport_is_genuinely_too_narrow():
    from czjLLM.job_manager.win_gui import fit_document_column_widths
    minimums = (205, 115, 182, 270, 55, 55, 91)
    for viewport in (400, 760, 920, 984):
        widths, scroll = fit_document_column_widths(viewport, minimums)
        assert scroll and widths == minimums
    for invalid in ((), (0, 3, 4, 5, 6, 7, 8)):
        import pytest
        with pytest.raises(ValueError):
            fit_document_column_widths(1300, invalid)


def test_document_grid_reflows_on_configure_without_tk_auto_stretch():
    src = inspect.getsource(win_gui._gui_proc_main)
    assert 'document_grid.bind("<Configure>", _resize_document_columns)' in src
    assert 'heading_font.measure(title_text)' in src
    assert 'fit_document_column_widths(width, document_mins)' in src
    assert 'width=minimum, minwidth=minimum' in src
    assert 'stretch=False' in src
    assert 'document_xscroll.pack_forget()' in src
    assert 'document_xscroll.pack(fill="x", after=document_grid)' in src
    assert 'document_grid.column(col, width=target)' in src
    assert 'rowheight=max(28, document_line_height + 10)' in src
    assert 'cancel_event.set()' in src
