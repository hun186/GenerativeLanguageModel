"""Shared Tk review window. All widgets live in the existing GUI process."""
from __future__ import annotations

import queue
import threading


_LABELS = {
    "open": "待檢閱", "ignored": "已忽略（不影響執行）",
    "deleted": "已從檢閱清單隱藏", "resolved": "檢閱已結案",
    "blocked": "仍隔離", "pending": "回到 TODO（尚未完成）",
    "absent": "無復原檔", "unknown": "證據不可讀",
}


def show_recovery_review(parent, meter_path_provider, extra_dirs_provider=lambda: ()):
    """Open independently per Windows GUI instance; never mutate queue state."""
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
    from czjLLM.job_manager.recovery_review import (
        list_review_items, set_review_action,
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
    rows = []
    by_id = {}
    manual_dirs = set()
    pending = queue.Queue(maxsize=1)
    busy = [False]

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

    def render():
        grid.delete(*grid.get_children())
        by_id.clear()
        for index, item in enumerate(rows, 1):
            # Active blocked or unreadable evidence can NEVER disappear from
            # the interface even after the operator presses Ignore/Delete.
            if (item["review_state"] == "deleted"
                    and item["operational"] not in {"blocked", "unknown"}
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
        status.set(
            f"共 {len(rows)} 筆；顯示 {len(by_id)} 筆。"
            "隔離中的條目即使刪除檢閱紀錄也不會隱藏。"
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
                result = (True, list_review_items(meter, extras))
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
            rows[:] = result
            render()
        else:
            status.set(f"檢閱讀取失敗（{result}）；請檢查資料與權限。")

    def do_action(action):
        item = selected()
        if item is None:
            return
        if action == "resolved" and item["operational"] in {"blocked", "unknown"}:
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
            set_review_action(item["item_dir"], action)
        except Exception as exc:
            messagebox.showerror(
                "儲存失敗", f"未變更原始工作：{type(exc).__name__}",
                parent=win,
            )
            return
        refresh()

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
