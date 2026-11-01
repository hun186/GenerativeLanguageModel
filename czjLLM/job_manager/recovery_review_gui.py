"""Shared Tk review window. All widgets live in the existing GUI process."""
from __future__ import annotations

import queue
import threading


_LABELS = {
    "open": "待檢閱", "ignored": "已忽略（不影響執行）",
    "deleted": "已從檢閱清單隱藏", "resolved": "檢閱已結案",
    "blocked": "仍隔離", "pending": "回到 TODO（尚未完成）",
    "absent": "無復原檔", "unknown": "證據不可讀",
    "writeback_failure": "寫回失敗／待處理",
}


def show_recovery_review(parent, meter_path_provider, extra_dirs_provider=lambda: (),
                         audit_path_provider=lambda: ""):
    """Open independently per Windows GUI instance; never mutate queue state."""
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
    from czjLLM.job_manager.recovery_review import (
        list_review_items, set_review_action, format_incident_debug_report,
    )

    win = tk.Toplevel(parent)
    win.title("重大異常檢閱與處置")
    win.geometry("900x525")
    win.transient(parent)
    win.minsize(680, 360)
    frame = ttk.Frame(win, padding=10)
    frame.pack(fill="both", expand=True)
    ttk.Label(
        frame,
        text="此處只管理檢閱狀態；已解決≠SQL/ES寫回完成。"
             "忽略／刪除紀錄不解除隔離、不刪除 TODO/RUNNING/Success。",
        foreground="#9b3c18", wraplength=850,
    ).pack(anchor="w", pady=(0, 8))

    controls = ttk.Frame(frame)
    controls.pack(fill="x", pady=(0, 6))
    status = tk.StringVar(value="讀取中…")
    show_hidden = tk.BooleanVar(value=False)
    include_local_paths = tk.BooleanVar(value=False)
    rows = []
    by_id = {}
    manual_dirs = set()
    pending = queue.Queue(maxsize=1)
    busy = [False]
    review_page = [0]
    review_pages = [1]
    review_candidates = [0]
    diagnostic_busy = [False]
    diagnostic_result = queue.Queue(maxsize=1)

    grid = ttk.Treeview(
        frame,
        columns=("number", "code", "runtime", "review", "checks"),
        show="headings", selectmode="browse",
    )
    for col, text, size in (
        ("number", "序號", 65),
        ("code", "異常代碼", 260),
        ("runtime", "實際任務狀態", 200),
        ("review", "檢閱處置", 220),
        ("checks", "復查次數", 100),
    ):
        grid.heading(col, text=text)
        grid.column(col, width=size, anchor="w", stretch=col != "number")
    grid.pack(fill="both", expand=True)
    paging = ttk.Frame(frame)
    paging.pack(fill="x", pady=(4, 0))
    page_prev = ttk.Button(paging, text="上一頁")
    page_prev.pack(side="left", padx=(0, 5))
    page_next = ttk.Button(paging, text="下一頁")
    page_next.pack(side="left")
    page_label = ttk.Label(paging, text="第 1/1 頁")
    page_label.pack(side="left", padx=(12, 0))

    def render():
        children = grid.get_children()
        if children:
            grid.delete(*children)
        by_id.clear()
        for index, item in enumerate(rows, 1):
            # Active blocked or unreadable evidence can NEVER disappear from
            # the interface even after the operator presses Ignore/Delete.
            if (item["review_state"] == "deleted"
                    and item["operational"] not in {
                        "blocked", "unknown", "writeback_failure",
                    }
                    and not show_hidden.get()):
                continue
            iid = str(index)
            by_id[iid] = item
            grid.insert("", "end", iid=iid, values=(
                index, item["code"],
                _LABELS.get(item["operational"], item["operational"]),
                _LABELS.get(item["review_state"], item["review_state"]),
                item["recheck_count"],
            ))
        page_label.configure(
            text=f"第 {review_page[0] + 1}/{review_pages[0]} 頁"
        )
        page_prev.configure(
            state="normal" if review_page[0] > 0 else "disabled"
        )
        page_next.configure(
            state="normal" if review_page[0] + 1 < review_pages[0]
            else "disabled"
        )
        status.set(
            f"目前頁 {len(rows)} 筆候選，實際顯示 {len(by_id)} 筆；"
            f"全部工作候選 {review_candidates[0]} 筆。"
            "只掃描目前頁，已知寫回／隔離異常優先。"
        )

    def selected():
        selection = grid.selection()
        if not selection or selection[0] not in by_id:
            messagebox.showinfo("請選取條目", "請先點選要檢閱的條目。", parent=win)
            return None
        return by_id[selection[0]]

    def refresh():
        if busy[0] or not win.winfo_exists():
            return
        busy[0] = True
        status.set("正在掃描目前任務的異常狀態…")
        meter = meter_path_provider()
        extras = tuple(manual_dirs) + tuple(extra_dirs_provider())
        def work():
            try:
                result = (True, list_review_items(
                    meter, extras, page=review_page[0], with_paging=True,
                ))
            except Exception as exc:
                result = (False, type(exc).__name__)
            pending.put(result)
        threading.Thread(target=work, name="queue-review-reader", daemon=True).start()

    def poll():
        if not win.winfo_exists():
            return
        try:
            ok, result = pending.get_nowait()
        except queue.Empty:
            win.after(100, poll)
            return
        busy[0] = False
        if ok:
            rows[:] = result["items"]
            review_page[0] = result["page"]
            review_pages[0] = result["pages"]
            review_candidates[0] = result["total_candidates"]
            render()
        else:
            status.set(f"檢閱讀取失敗（{result}）；請檢查資料與權限。")
        # Keep polling for every subsequent Refresh, manual directory add
        # and operator action, not only while the first read is pending.
        win.after(100, poll)

    def turn_review_page(delta):
        review_page[0] = max(0, min(
            review_pages[0] - 1, review_page[0] + delta,
        ))
        refresh()

    page_prev.configure(command=lambda: turn_review_page(-1))
    page_next.configure(command=lambda: turn_review_page(1))

    def do_action(action):
        item = selected()
        if item is None:
            return
        if action == "resolved" and item["operational"] in {
            "blocked", "unknown", "writeback_failure",
        }:
            messagebox.showwarning(
                "仍有未解除的安全問題",
                "該項目仍處於隔離或證據不可讀，不能標記為已解決。"
                "請先安全處理原始工作，再重新整理。",
                parent=win,
            )
            return
        if action == "deleted" and not messagebox.askyesno(
            "確認隱藏檢閱紀錄",
            "這只會新增一筆檢閱隱藏記錄，不會刪除異常證據、Queue、"
            "Success 或安全告警。仍在 Blocked 的項目會持續顯示。",
            parent=win,
        ):
            return
        try:
            set_review_action(
                item["item_dir"], action,
                row_status=item.get("source_row_status"),
            )
        except Exception as exc:
            messagebox.showerror(
                "儲存失敗", f"未變更原始工作：{type(exc).__name__}",
                parent=win,
            )
            return
        refresh()

    def _copy_debug_report(items):
        # The formatter accepts whitelisted metadata ONLY. Never pass paths
        # or raw meter JSON to Tk clipboard; no network calls or file writes.
        try:
            report = format_incident_debug_report(items)
            win.clipboard_clear()
            win.clipboard_append(report)
            win.update_idletasks()  # Keep clipboard available after closing.
            status.set(f"已複製 {len(items)} 筆去識別化診斷資訊，可貼到 ChatGPT。")
        except Exception as exc:
            messagebox.showerror(
                "複製診斷資訊失敗", type(exc).__name__, parent=win,
            )

    def _copy_detailed_debug(items):
        if diagnostic_busy[0]:
            status.set("詳細診斷仍在採集，請先完成目前這次複製。")
            return
        if not items:
            messagebox.showinfo("請選取條目", "請先選擇異常條目。", parent=win)
            return
        include_paths = include_local_paths.get()
        if include_paths and not messagebox.askyesno(
            "包含本機路徑？",
            "完整路徑與 Run／任務 ID 可能包含使用者名稱或其他敏感資訊。"
            "確定要將路徑加入剪貼簿嗎？貼到 ChatGPT 前請再檢查。",
            parent=win,
        ):
            return
        diagnostic_busy[0] = True
        status.set("正在背景採集詳細診斷證據（不會讀取 Prompt 或 SQL/ES 資料）…")
        meter = meter_path_provider()
        audit = audit_path_provider()
        snapshot = tuple(dict(item) for item in items)
        def work():
            try:
                from czjLLM.job_manager.incident_diagnostics import (
                    build_detailed_debug_report,
                )
                report = build_detailed_debug_report(
                    snapshot, meter_path=meter, audit_path=audit,
                    include_paths=include_paths,
                )
                diagnostic_result.put((True, report))
            except Exception as exc:
                diagnostic_result.put((False, type(exc).__name__))
        threading.Thread(
            target=work, name="incident-diagnostic-reader", daemon=True,
        ).start()
        win.after(100, _poll_diagnostic)

    def _poll_diagnostic():
        if not win.winfo_exists():
            return
        try:
            ok, result = diagnostic_result.get_nowait()
        except queue.Empty:
            win.after(100, _poll_diagnostic)
            return
        diagnostic_busy[0] = False
        if not ok:
            messagebox.showerror("詳細診斷失敗", result, parent=win)
            return
        try:
            win.clipboard_clear()
            win.clipboard_append(result)
            win.update_idletasks()
            status.set("已複製完整診斷包；請貼到 ChatGPT，必要時先檢查本機路徑。")
        except Exception as exc:
            messagebox.showerror(
                "剪貼簿失敗", type(exc).__name__, parent=win,
            )

    def _copy_selected_detailed():
        item = selected()
        if item is not None:
            _copy_detailed_debug([item])

    def _copy_selected_debug():
        item = selected()
        if item is not None:
            _copy_debug_report([item])

    def _copy_visible_debug():
        visible = list(by_id.values())
        if not visible:
            messagebox.showinfo("沒有可複製資料", "目前沒有顯示中的異常條目。", parent=win)
            return
        _copy_debug_report(visible)

    # Separate copy row avoids squeezing the existing review actions on a
    # narrow/DPI-scaled Windows window.
    copy_controls = ttk.Frame(frame)
    copy_controls.pack(fill="x", pady=(0, 6))
    ttk.Button(
        copy_controls, text="📋 複製選取條目（ChatGPT 除錯）",
        command=_copy_selected_debug,
    ).pack(side="left", padx=(0, 8))
    ttk.Button(
        copy_controls, text="📋 複製目前顯示的異常摘要",
        command=_copy_visible_debug,
    ).pack(side="left")
    detail_controls = ttk.Frame(frame)
    detail_controls.pack(fill="x", pady=(0, 6))
    ttk.Button(
        detail_controls, text="📋 複製選取條目的完整除錯包",
        command=_copy_selected_detailed,
    ).pack(side="left", padx=(0, 8))
    ttk.Checkbutton(
        detail_controls, text="含路徑、Run ID、任務 ID（敏感；預設關閉）",
        variable=include_local_paths,
    ).pack(side="left")

    ttk.Button(controls, text="重新整理", command=refresh).pack(
        side="left", padx=(0, 6))
    ttk.Button(controls, text="已解決", command=lambda: do_action("resolved")).pack(
        side="left", padx=(0, 5))
    ttk.Button(controls, text="忽略", command=lambda: do_action("ignored")).pack(
        side="left", padx=(0, 5))
    ttk.Button(controls, text="刪除檢閱紀錄", command=lambda: do_action("deleted")).pack(
        side="left", padx=(0, 5))
    ttk.Button(controls, text="重新開啟", command=lambda: do_action("open")).pack(
        side="left", padx=(0, 5))
    ttk.Checkbutton(
        controls, text="顯示隱藏紀錄", variable=show_hidden,
        command=render,
    ).pack(side="right")

    def choose_item_directory():
        directory = filedialog.askdirectory(
            parent=win, title="選擇要檢閱的單一工作目錄（僅檢查，不掃描整顆磁碟）",
        )
        if directory:
            manual_dirs.add(directory)
            refresh()

    ttk.Button(
        frame, text="加入舊工作目錄…", command=choose_item_directory,
    ).pack(anchor="w", pady=(8, 0))
    ttk.Label(frame, textvariable=status, foreground="#555").pack(
        anchor="w", pady=(5, 0))
    win.after(80, poll)
    refresh()
    return win
