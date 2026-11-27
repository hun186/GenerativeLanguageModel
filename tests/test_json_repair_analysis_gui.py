"""JSON repair comparisons from real Worker strings to privacy-safe GUI events."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from czjLLM.job_manager.win_gui import (
    format_json_repair_analysis_case,
    format_json_repair_analysis_case_detail,
    format_json_repair_analysis_summary,
)
from czjLLM.utilities.json_repair_analysis import (
    MAX_ANALYSIS_CHARS, analyze_json_repair, validate_repair_detail,
)
from czjLLM.utilities.processing_quality import (
    QualityAccumulator, emit_quality_event, quality_event_path,
)
from czjLLM.utilities.processing_quality_run_reader import QualityRunTailReader
from czjLLM.utilities.processing_quality_rotation import rotate_quality_event_stream


def _analyze(original, repaired):
    with pytest.raises(json.JSONDecodeError) as exc:
        json.loads(original)
    json.loads(repaired)
    code, metrics = analyze_json_repair(original, repaired, exc.value)
    assert validate_repair_detail(metrics)
    return code, metrics


def test_missing_comma_and_bracket_only_preserve_literal_tokens():
    code, m = _analyze('{"a":1 "b":2}', '{"a":1,"b":2}')
    assert code == "JSON_REPAIR_SYNTAX_CANDIDATE"
    assert m["same_literal_pct"] == 100
    assert m["before_key_patterns"] == m["after_key_patterns"] == 2
    code, m = _analyze('[{"name":"敏感", "score":1}', '[{"name":"敏感", "score":1}]')
    assert code == "JSON_REPAIR_SYNTAX_CANDIDATE"
    assert m["same_literal_pct"] == 100


def test_unterminated_string_tail_has_distinct_unverified_content_warning():
    code, m = _analyze('{"name":"在這裡被切', '{"name":"在這裡被切完"}')
    assert code == "JSON_REPAIR_TAIL_CANDIDATE"
    assert m["error_kind"] == "UNTERMINATED_STRING"
    assert m["error_pos_pct"] < 100  # parser points to starting quote
    assert m["common_prefix_chars"] == m["original_chars"]


def test_changed_content_is_not_mislabeled_as_punctuation_repair():
    code, m = _analyze('{"a":"source" "b":1}', '{"a":"changed","b":1}')
    assert code in {"JSON_REPAIR_CONTENT_EDIT", "JSON_REPAIR_LARGE_CHANGE"}
    assert m["same_literal_pct"] < 100
    code, m = _analyze(
        '{"a":"alpha" "b":"bravo", "c":"charlie"}',
        '{"a":"entirely new text","k":"new data"}',
    )
    assert code == "JSON_REPAIR_LARGE_CHANGE"
    assert m["before_key_patterns"] > m["after_key_patterns"]


def test_bounded_analysis_refuses_huge_input_without_storing_any_payload():
    original = '{"a":"' + ("sensitive" * 18_000)
    repaired = json.dumps({"a": "sensitive" * 18_000}, ensure_ascii=False)
    code, m = _analyze(original, repaired)
    assert len(original) > MAX_ANALYSIS_CHARS
    assert code == "JSON_REPAIR_COMPARISON_UNAVAILABLE"
    assert m["same_literal_pct"] == 0
    assert not any(isinstance(v, str) and "sensitive" in v for v in m.values())


def test_event_reader_gui_aggregates_and_rotates_without_payload(tmp_path):
    audit = tmp_path / "llm_call_audit_run-A.csv"
    original = '{"secret":"此處是私人文字" "v":2}'
    repaired = '{"secret":"此處是私人文字","v":2}'
    code, detail = _analyze(original, repaired)
    emit_quality_event(
        str(audit), run_id="a", event="slice_json_repair",
        code="JSON_REPAIR_SUCCEEDED", scope="slice", outcome="recovered",
        slice_id=str(tmp_path / "TODO" / "row-sensitive-42.txt"),
        detail=dict(detail, repair_class=code),
    )
    event_file = quality_event_path(str(audit))
    event_text = event_file.read_text(encoding="utf-8")
    assert "私人文字" not in event_text
    assert "row-sensitive" in event_text  # pre-existing stream uses basename
    assert "secret" not in event_text
    reader = QualityRunTailReader(str(event_file))
    changed, stats = reader.poll()
    assert changed
    assert stats["repair_analysis_count"] == 1
    assert stats["repair_analysis_categories"][code] == 1
    assert stats["repair_success_pct"] == 100.0  # same event, no extra identity
    assert len(stats["repair_analysis_recent"]) == 1
    recent = stats["repair_analysis_recent"][0]
    assert "row-sensitive" not in json.dumps(recent, ensure_ascii=False)
    assert len(recent["slice_hint"]) == 24
    assert len(recent["work_item_hint"]) == 24
    assert recent["lineage_status"] == "ITEM_PATH_DERIVED"
    assert recent["run_id"] == "a"
    assert len(recent["event_hint"]) == 12
    assert len(recent["event_id"]) == 32
    assert "疑似符號修補 1" in format_json_repair_analysis_summary(stats)
    assert format_json_repair_analysis_case(recent)[6].startswith(str(len(original)))
    assert format_json_repair_analysis_case(recent)[1] == "a"
    assert format_json_repair_analysis_case(recent)[2] == recent["work_item_hint"]
    assert format_json_repair_analysis_case(recent)[3] == recent["slice_hint"]
    assert format_json_repair_analysis_case(recent)[4] == recent["event_hint"]
    assert "原始解析錯誤" in format_json_repair_analysis_case_detail(recent)
    assert reader.poll()[0] is False
    rotate_quality_event_stream(audit)
    assert reader.poll()[1]["repair_analysis_count"] == 1
    assert reader.poll()[1]["repair_analysis_recent"] == stats["repair_analysis_recent"]


def test_quality_rejects_payload_injected_via_detail_before_writing_or_counting(tmp_path):
    audit = tmp_path / "llm_call_audit_security.csv"
    code, m = _analyze('{"a":1,}', '{"a":1}')
    with pytest.raises(ValueError, match="scalar detail"):
        emit_quality_event(
            str(audit), event="slice_json_repair", code="JSON_REPAIR_SUCCEEDED",
            scope="slice", outcome="recovered",
            detail={**m, "repair_class": code, "raw_output": "secret"},
        )
    assert not quality_event_path(str(audit)).exists()
    acc = QualityAccumulator()
    assert acc.add({
        "schema_version": 1, "event_id": "spoof",
        "event": "slice_json_repair", "scope": "slice",
        "code": "JSON_REPAIR_SUCCEEDED",
        "detail": {**m, "repair_class": code, "raw_output": "secret"},
    }) is False
    assert acc.snapshot()["events"] == 0


def test_real_worker_handler_emits_success_and_comparison_without_payload(
    monkeypatch, tmp_path, capsys,
):
    import czjLLM.prompt_pipeline.pipeline_controller as pc

    audit = tmp_path / "llm_call_audit_live.csv"
    before = '{"confidential":"內部秘密" "count":2}'
    after = '{"confidential":"內部秘密","count":2}'
    monkeypatch.setattr(pc, "json_format_caller", lambda **kw: after)
    # A real PromptAPIPipeline constructor reads an on-disk prompt when
    # content="" and promptFile is set. Supply a synthetic local fixture.
    prompt = tmp_path / "RUNNING" / "row.txt"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("synthetic-json-repair-fixture", encoding="utf-8")
    worker = pc.PromptAPIPipeline(
        task="to json", content="",
        promptFile=str(prompt),
        model_spec={"model_name": "mock-model", "base_url": ["http://invalid.local"]},
        audit_run_id="this-run", audit_path=str(audit),
    )
    monkeypatch.setattr(
        worker, "extract_MainFileName_and_input_text",
        lambda: ("", "", ""),
    )
    retry, result = worker.handle_json_output(before)
    assert retry == [] and result == after
    text = capsys.readouterr().out
    assert "內部秘密" not in text
    records = [
        json.loads(line)
        for line in quality_event_path(str(audit)).read_text(encoding="utf-8").splitlines()
    ]
    assert [r["event"] for r in records] == [
        "slice_json_validation", "slice_json_repair",
    ]
    assert records[-1]["detail"]["repair_class"] == (
        "JSON_REPAIR_SYNTAX_CANDIDATE"
    )
    acc = QualityAccumulator()
    for record in records:
        assert acc.add(record)
    snap = acc.snapshot()
    assert snap["slice_initial_invalid"] == 1
    assert snap["repair_succeeded"] == 1
    assert snap["repair_analysis_count"] == 1


def test_gui_wiring_uses_contextual_button_and_dedicated_popup_not_a_static_row():
    gui = Path("czjLLM/job_manager/win_gui.py").read_text(encoding="utf-8")
    popup = Path("czjLLM/job_manager/json_repair_review_gui.py").read_text(encoding="utf-8")
    assert "repair_analysis_section = ttk.Frame(quality_section)" not in gui
    assert "repair_analysis_tree = ttk.Treeview" not in gui
    assert "repair_analysis_button = tk.Button(" in gui
    assert 'text="🔎 JSON 差異"' in gui
    assert "repair_analysis_button.grid_remove()" in gui
    assert "quality_summary_row.columnconfigure(0, weight=1)" in gui
    assert "repair_analysis_button.grid(row=0, column=1" in gui
    assert "row_width - reserve - 8" in gui
    assert "quality_summary.grid(row=0, column=0" in gui
    assert "from czjLLM.job_manager.json_repair_review_gui import show_json_repair_review" in gui
    # Import happens at Windows GUI process entry, not inside the popup
    # exception guard (AGENTS.md); avoid obscured import failures.
    opener = gui[gui.index("    def _open_json_repair_review():"):
                 gui.index("    repair_analysis_button = tk.Button(")]
    assert "from czjLLM.job_manager.json_repair_review_gui import" not in opener
    assert "show_json_repair_review(" in gui
    assert "refresh_repair_analysis()" in gui
    assert '("run", "run_id", 180)' in popup
    assert '("item", "工作項目提示碼", 205)' in popup
    assert '("slice", "切片追蹤提示碼", 205)' in popup
    assert '("event", "單次修復事件", 130)' in popup
    assert "疑似鍵名片段數" in popup
    assert 'orient="horizontal"' in popup
    assert 'orient="vertical"' in popup
    assert 'rowheight=max(27, int(font.metrics("linespace")) + 11)' in popup
    assert "change_map_segments(case)" in popup
    assert 'heading.bind("<Configure>", resize_header)' in popup
    assert 'summary.configure(wraplength=wrap)' in popup
    assert 'disclaimer.configure(wraplength=wrap)' in popup
    assert 'wraplength=max(180, int(event.width) - 24)' in popup
    assert "字面值相同率" in gui



def test_large_escaped_quote_malformed_string_scans_in_linear_time():
    import time

    # Previously key-pattern regex repeatedly rescanned every escaped quote.
    original = '{"x":"' + '\\"' * 12_000
    repaired = original + '"}'
    start = time.monotonic()
    code, m = _analyze(original, repaired)
    elapsed = time.monotonic() - start
    assert code == "JSON_REPAIR_TAIL_CANDIDATE"
    assert m["before_key_patterns"] == m["after_key_patterns"] == 1
    assert elapsed < 3.0

def test_identical_slice_basename_keeps_distinct_event_ids_and_run_context(tmp_path):
    audit = tmp_path / "llm_call_audit_run-42.csv"
    code, detail = _analyze('{"a":1,}', '{"a":1}')
    for i in range(2):
        emit_quality_event(
            str(audit), run_id="task-run-42",
            event="slice_json_repair", code="JSON_REPAIR_SUCCEEDED",
            scope="slice", outcome="recovered",
            slice_id=str(tmp_path / ("different-folder-" + str(i)) / "TODO" / "1.txt"),
            detail=dict(detail, repair_class=code),
        )
    reader = QualityRunTailReader(str(quality_event_path(str(audit))))
    _changed, stats = reader.poll()
    cases = stats["repair_analysis_recent"]
    assert len(cases) == 2
    assert cases[0]["slice_hint"] != cases[1]["slice_hint"]
    assert cases[0]["work_item_hint"] != cases[1]["work_item_hint"]
    assert all(x["lineage_status"] == "ITEM_PATH_DERIVED" for x in cases)
    assert cases[0]["event_id"] != cases[1]["event_id"]
    assert cases[0]["event_hint"] != cases[1]["event_hint"]
    assert all(x["run_id"] == "task-run-42" for x in cases)


@pytest.mark.parametrize("viewer, normal_limit", [
    ("review", (1160, 600)),
    ("raw", (1200, 720)),
])
def test_windows_repair_viewer_native_maximize_and_restore(viewer, normal_limit):
    """Exercise the actual Tk windows on a Windows desktop when available."""
    import sys
    import tkinter as tk
    if sys.platform != "win32":
        pytest.skip("native Windows title-bar contract")
    from czjLLM.job_manager.json_repair_review_gui import show_json_repair_review
    from czjLLM.job_manager.json_repair_raw_diff_gui import show_private_json_diff
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable")
    try:
        root.geometry("400x300")
        root.update()
        if viewer == "review":
            win = show_json_repair_review(
                root, lambda: {}, lambda case: (), lambda stats: "",
                lambda case: "",
            )
            expected = (min(normal_limit[0], max(760, win.winfo_screenwidth()) - 80),
                        min(normal_limit[1], max(460, win.winfo_screenheight()) - 100))
        else:
            win = show_private_json_diff(root, '{"a":1,}', '{"a":1}')
            expected = (min(normal_limit[0], max(850, win.winfo_screenwidth()) - 80),
                        min(normal_limit[1], max(520, win.winfo_screenheight()) - 110))
        root.update()
        assert win.state() == "zoomed"
        assert not win.transient()
        assert all(int(value) for value in win.resizable())
        from czjLLM.job_manager.json_repair_window import _win32_frame_handles
        import ctypes
        from ctypes import wintypes

        def assert_native_owner():
            user32, frame, owner_frame = _win32_frame_handles(win, root)
            get_window = user32.GetWindow
            get_window.argtypes = (wintypes.HWND, wintypes.UINT)
            get_window.restype = wintypes.HWND
            assert get_window(frame, 4) == owner_frame
            get_style = user32.GetWindowLongW
            get_style.argtypes = (wintypes.HWND, ctypes.c_int)
            get_style.restype = ctypes.c_long
            assert get_style(frame, -16) & 0x00010000  # WS_MAXIMIZEBOX
            assert not get_style(frame, -20) & 0x00000008  # WS_EX_TOPMOST

        assert_native_owner()
        root.lift()
        root.update()
        assert_native_owner()
        assert not win.overrideredirect()
        assert not int(win.attributes("-fullscreen"))
        win.state("normal")
        root.update()
        assert_native_owner()
        # Existing minimum sizes still constrain tiny displays.
        min_w, min_h = win.minsize()
        assert (win.winfo_width(), win.winfo_height()) == (
            max(expected[0], min_w), max(expected[1], min_h))
        win.state("zoomed")
        root.update()
        assert win.state() == "zoomed"
        assert_native_owner()
        win.destroy()
        root.update()
        assert not win.winfo_exists()
        assert root.winfo_exists()
    finally:
        root.destroy()


@pytest.mark.parametrize("path, owner", [
    ("json_repair_review_gui.py", "parent"),
    ("json_repair_raw_diff_gui.py", "owner"),
])
def test_repair_viewer_window_management_wiring(path, owner):
    """Headless regression; no Tk display or raw source access required."""
    source = (Path("czjLLM/job_manager") / path).read_text(encoding="utf-8")
    assert 'native_maximize = win.tk.call("tk", "windowingsystem") == "win32"' in source
    assert f"    else:\n        win.transient({owner})" in source
    assert 'if native_maximize:\n        win.resizable(True, True)' in source
    assert 'win.state("zoomed")' in source
    assert f"retain_win32_viewer_owner(win, {owner})" in source
    assert source.index("win.geometry(") < source.index('win.state("zoomed")')
    assert "overrideredirect(" not in source
    assert 'attributes("-fullscreen"' not in source


def test_raw_diff_wrap_switch_controls_both_panes_without_editing():
    """Exercise the real switching helper without requiring a desktop."""
    from unittest.mock import Mock, call
    from czjLLM.job_manager.json_repair_raw_diff_gui import _set_wrap_mode

    panes = [(Mock(), Mock()), (Mock(), Mock())]
    _set_wrap_mode(panes, True)
    _set_wrap_mode(panes, False)
    _set_wrap_mode(panes, True)
    for text, bar in panes:
        assert text.mock_calls == [
            call.configure(wrap="char"), call.xview_moveto(0),
            call.configure(wrap="none"),
            call.configure(wrap="char"), call.xview_moveto(0),
        ]
        assert bar.mock_calls == [
            call.grid_remove(), call.grid(), call.grid_remove(),
        ]


def test_raw_diff_wrap_checkbox_preserves_exact_json_and_tags():
    """Actual Tk integration when a desktop is available; no private data."""
    import tkinter as tk
    from tkinter import ttk
    from czjLLM.job_manager.json_repair_raw_diff_gui import show_private_json_diff

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable")
    original = '{"value":"' + ("中文ABC" * 300) + '",}'
    repaired = original.replace('",}', '"}')
    try:
        root.update()
        win = show_private_json_diff(root, original, repaired)
        root.update()

        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)

        children = list(descendants(win))
        texts = [w for w in children if isinstance(w, tk.Text)]
        bars = [w for w in children if isinstance(w, ttk.Scrollbar)
                and str(w.cget("orient")) == "horizontal"]
        toggles = [w for w in children if isinstance(w, ttk.Checkbutton)
                   and "Wrap" in str(w.cget("text"))]
        assert len(texts) == len(bars) == 2
        assert len(toggles) == 1
        before_tags = [(w.tag_ranges("same"), w.tag_ranges("changed")) for w in texts]

        def assert_mode(mode, manager):
            for w, exact in zip(texts, (original, repaired)):
                assert str(w.cget("wrap")) == mode
                assert w.get("1.0", "end-1c") == exact
                assert str(w.cget("state")) == "disabled"
                assert not int(w.cget("exportselection"))
            assert [(w.tag_ranges("same"), w.tag_ranges("changed"))
                    for w in texts] == before_tags
            assert all(bar.winfo_manager() == manager for bar in bars)

        assert_mode("char", "")
        toggles[0].invoke()
        root.update()
        assert_mode("none", "grid")
        toggles[0].invoke()
        root.update()
        assert_mode("char", "")
        # A new view has its own independent default, not shared global state.
        toggles[0].invoke()
        other = show_private_json_diff(root, original, repaired)
        root.update()
        assert all(str(w.cget("wrap")) == "char" for w in descendants(other)
                   if isinstance(w, tk.Text))
        assert_mode("none", "grid")
        other.destroy()
        win.destroy()
    finally:
        root.destroy()


def test_raw_diff_wrap_control_is_wired_to_actual_panes():
    source = Path("czjLLM/job_manager/json_repair_raw_diff_gui.py").read_text(encoding="utf-8")
    assert 'tk.BooleanVar(master=win, value=True)' in source
    assert 'command=lambda: _set_wrap_mode(panes, wrap_enabled.get())' in source
    assert 'panes.append((txt, scroll_x))' in source
    assert '    _set_wrap_mode(panes, wrap_enabled.get())\n    footer' in source


def test_json_viewer_focus_guard_only_allows_main_widgets():
    from unittest.mock import Mock
    import tkinter as tk
    from czjLLM.job_manager.json_repair_window import main_window_has_focus

    root = Mock()
    focused = Mock()
    root.focus_displayof.return_value = focused
    focused.winfo_toplevel.return_value = root
    assert main_window_has_focus(root)
    focused.winfo_toplevel.return_value = Mock()
    assert not main_window_has_focus(root)
    root.focus_displayof.return_value = None
    assert not main_window_has_focus(root)
    root.focus_displayof.side_effect = tk.TclError("window closed")
    assert not main_window_has_focus(root)


def test_json_viewer_owner_failure_restores_safe_transient(monkeypatch):
    from unittest.mock import Mock
    from czjLLM.job_manager import json_repair_window as windows

    win, parent = Mock(), Mock()
    win.winfo_exists.return_value = True
    attach = Mock(side_effect=OSError("native wrapper unavailable"))
    monkeypatch.setattr(windows, "_attach_win32_owner", attach)
    assert not windows.retain_win32_viewer_owner(win, parent)
    win.state.assert_called_once_with("normal")
    win.transient.assert_called_once_with(parent)
    attach.assert_called_once_with(win, parent)
    attach.side_effect = None
    win.reset_mock()
    assert windows.retain_win32_viewer_owner(win, parent)
    win.state.assert_not_called()
    win.transient.assert_not_called()


def test_main_tooltip_guard_runs_before_creating_window():
    source = Path("czjLLM/job_manager/win_gui.py").read_text(encoding="utf-8")
    opener = source.split("    def _open_json_repair_review():", 1)[1].split(
        "    repair_analysis_button = ", 1)[0]
    assert "_hide_audit_tooltip()" in opener
    tooltip = source.split("    def _show_audit_tooltip(", 1)[1].split(
        "    def _audit_canvas_layout_width", 1)[0]
    assert tooltip.index("if not main_window_has_focus(root):") < tooltip.index(
        "tk.Toplevel(root)")
    assert 'root.bind("<FocusOut>"' in source


def test_windows_nested_json_viewers_stay_above_both_owners():
    """Check real native Z order after simulated owner raises, not just links."""
    import sys
    import tkinter as tk
    from ctypes import wintypes
    if sys.platform != "win32":
        pytest.skip("native Windows Z-order contract")
    from czjLLM.job_manager.json_repair_review_gui import show_json_repair_review
    from czjLLM.job_manager.json_repair_raw_diff_gui import show_private_json_diff
    from czjLLM.job_manager.json_repair_window import _win32_frame_handles

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable")
    try:
        root.update()
        review = show_json_repair_review(
            root, lambda: {}, lambda case: (), lambda stats: "", lambda case: "",
        )
        raw = show_private_json_diff(review, '{"a":1,}', '{"a":1}')
        root.update()

        def assert_above(child, owner):
            user32, frame, owner_frame = _win32_frame_handles(child, owner)
            get_window = user32.GetWindow
            get_window.argtypes = (wintypes.HWND, wintypes.UINT)
            get_window.restype = wintypes.HWND
            assert get_window(frame, 4) == owner_frame  # GW_OWNER
            # GW_HWNDPREV walks toward higher windows. Bound the walk even
            # if an unrelated window is destroyed during enumeration.
            cursor = owner_frame
            seen = set()
            while cursor and cursor not in seen and len(seen) < 2048:
                seen.add(cursor)
                cursor = get_window(cursor, 3)
                if cursor == frame:
                    break
            assert cursor == frame, "owned viewer must stay above its owner"

        def assert_chain():
            assert_above(review, root)
            assert_above(raw, review)
            assert raw.state() == "zoomed"

        assert_chain()
        root.lift()
        root.update()
        assert_chain()
        review.lift()
        root.update()
        assert_chain()
        raw.destroy()
        root.update()
        assert review.winfo_exists() and root.winfo_exists()
        assert_above(review, root)
    finally:
        root.destroy()


def test_explicit_success_methods_keep_unmarked_history_distinct(tmp_path):
    from czjLLM.utilities.processing_quality_disk_spill import DiskBackedQualityAccumulator
    audit = tmp_path / "llm_call_audit_methods.csv"
    code, detail = _analyze('{"a":1,}', '{"a":1}')
    for method in ("RULE_BASED", "LLM_BASED", None):
        fields = dict(detail, repair_class=code)
        if method is not None:
            fields["repair_method"] = method
        emit_quality_event(str(audit), run_id="method-test", event="slice_json_repair",
                           code="JSON_REPAIR_SUCCEEDED", scope="slice", outcome="recovered",
                           detail=fields)
    emit_quality_event(str(audit), run_id="method-test", event="slice_json_repair",
                       code="JSON_REPAIR_SUCCEEDED", scope="slice", outcome="recovered")
    emit_quality_event(str(audit), run_id="method-test", event="slice_json_repair",
                       code="JSON_REPAIR_FAILED", scope="slice", outcome="not_recovered")
    records = [json.loads(line) for line in quality_event_path(str(audit)).read_text(encoding="utf-8").splitlines()]
    expected = {"RULE_BASED": 1, "LLM_BASED": 1, "UNMARKED": 2}
    acc = QualityAccumulator()
    with DiskBackedQualityAccumulator() as disk:
        for record in records + records:
            acc.add(record)
            disk.add(record)
        assert acc.snapshot() == disk.snapshot()
    snapshot = acc.snapshot()
    assert snapshot["repair_success_methods"] == expected
    assert sum(expected.values()) == snapshot["repair_succeeded"] == 4
    assert snapshot["repair_attempts"] == 5
    assert snapshot["repair_analysis_count"] == 3
    summary = format_json_repair_analysis_summary(snapshot)
    assert "規則式 1｜LLM 1｜未標記 2" in summary
    assert "非各方法成功率" in summary
    cases = {case["detail"].get("repair_method"): case for case in snapshot["repair_analysis_recent"]}
    assert "修復方式：規則式" in format_json_repair_analysis_case_detail(cases["RULE_BASED"])
    assert "修復方式：LLM" in format_json_repair_analysis_case_detail(cases["LLM_BASED"])
    assert "修復方式：未標記" in format_json_repair_analysis_case_detail(cases[None])
    assert "規則式 1" not in format_json_repair_analysis_summary(dict(snapshot, quality_stream_status="unverified"))
    assert validate_repair_detail(dict(detail, repair_class=code, repair_method="LLM_BASED"))
    for invalid in ("LLM", "UNMARKED", [], True, "raw secret"):
        assert not validate_repair_detail(dict(detail, repair_class=code, repair_method=invalid))
