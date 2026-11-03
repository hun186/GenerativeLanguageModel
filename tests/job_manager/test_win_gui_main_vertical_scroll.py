"""Headless regressions for the entire Windows progress page overflow.

The outer page scroll is independent from the audit chart's drawing Canvas,
the row Treeview's horizontal scroll and the Log Text's vertical scroll.
Actual Windows DPI/monitor acceptance is still separately operator-gated.
"""
import inspect

import pytest

from czjLLM.job_manager import win_gui


@pytest.mark.parametrize(
    "content,viewport,required",
    [
        (200, 500, False),   # mostly collapsed
        (500, 500, False),   # exact fit, no wasted scrollbar
        (501, 500, True),    # one-pixel overrun must be reachable
        (1300, 900, True),  # quality and token sections expanded
        (2200, 900, True),  # all panels / document table expanded
        (760, 1200, False), # maximize or collapse restores available space
        (1500, 0, True),
        (0, 0, False),
    ],
)
def test_main_page_scrollbar_only_when_content_taller(content, viewport, required):
    assert win_gui.main_page_needs_vertical_scroll(content, viewport) is required


def test_main_page_height_contract_refuses_invalid_types():
    with pytest.raises(ValueError):
        win_gui.main_page_needs_vertical_scroll("100", 500)
    with pytest.raises(ValueError):
        win_gui.main_page_needs_vertical_scroll(500, None)


@pytest.mark.parametrize(
    "delta,units",
    [
        (120, -1),
        (-120, 1),
        (240, -2),
        (-360, 3),
        (1, -1),       # high-precision trackpad / fractional detents
        (-1, 1),
        (1200, -8),   # bounded huge deltas
        (0, 0),
    ],
)
def test_main_page_wheel_units_are_bounded_and_directional(delta, units):
    assert win_gui.main_page_mouse_wheel_units(delta) == units


def test_main_page_uses_separate_canvas_and_auto_vertical_scrollbar():
    src = inspect.getsource(win_gui._gui_proc_main)
    assert 'page_shell = ttk.Frame(root)' in src
    assert 'page_canvas = tk.Canvas(' in src
    assert 'page_canvas.pack(side="left", fill="both", expand=True)' in src
    assert 'page_scrollbar = ttk.Scrollbar(' in src
    assert 'command=page_canvas.yview' in src
    assert 'frm = ttk.Frame(page_canvas, padding=10)' in src
    assert 'page_window = page_canvas.create_window(' in src
    assert 'page_canvas.itemconfigure(page_window, width=max(1, int(event.width)))' in src
    assert 'content_height = max(1, int(frm.winfo_reqheight()))' in src
    assert 'viewport = int(page_canvas.winfo_height())' in src
    assert 'main_page_needs_vertical_scroll(' in src
    assert 'page_canvas.configure(' in src
    assert 'scrollregion=(0, 0, width, content_height)' in src
    assert 'page_scrollbar.pack(side="right", fill="y", before=page_canvas)' in src
    assert 'page_scrollbar.pack_forget()' in src
    assert 'page_canvas.yview_moveto(0)' in src
    assert 'frm.bind("<Configure>", _schedule_page_scroll_refresh)' in src
    assert 'page_canvas.bind("<Configure>", _page_viewport_resized)' in src
    assert 'root.after_idle(_refresh_page_scroll)' in src
    assert 'root.bind("<MouseWheel>", _on_page_mousewheel)' in src
    assert 'root.bind_all(' not in src


def test_native_text_tree_and_cancel_semantics_are_preserved():
    src = inspect.getsource(win_gui._gui_proc_main)
    # Main page must not steal native wheel events of Text or Treeview.
    assert 'isinstance(widget, (tk.Text, ttk.Treeview, ttk.Combobox))' in src
    assert 'page_scrollbar.winfo_manager()' in src
    assert 'widget.winfo_toplevel() is not root' in src
    assert 'page_canvas.yview_scroll(units, "units")' in src
    assert 'txt.configure(yscrollcommand=scr.set' in src
    assert 'scr = ttk.Scrollbar(frm, command=txt.yview)' in src
    assert 'document_grid.configure(xscrollcommand=document_xscroll.set)' in src
    assert 'cancel_event.set()' in src
    assert 'terminate(' not in src
    assert 'kill(' not in src
    assert 'root.geometry(f"{width}x{height}")' in src


def test_quality_token_document_sections_still_inside_page():
    src = inspect.getsource(win_gui._gui_proc_main)
    for section in ("quality", "audit", "document"):
        assert f'{section}_section = ttk.Frame(frm)' in src
        assert f'def _toggle_{section}():' in src
    assert 'audit_canvas = tk.Canvas(' in src
    assert 'audit_canvas.pack(fill="x", expand=True)' in src
    assert 'root.after_idle(_draw_audit_distribution)' in src
    assert 'document_grid = ttk.Treeview(' in src
