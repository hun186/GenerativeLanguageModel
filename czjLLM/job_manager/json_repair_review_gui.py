# -*- coding: utf-8 -*-
"""On-demand, run-scoped JSON repair viewer; no quality audit payloads."""
from __future__ import annotations

from tkinter import ttk
import tkinter as tk
from tkinter import messagebox
import tkinter.font as tkfont

from czjLLM.utilities.json_repair_change_map import change_map_segments
from czjLLM.utilities.json_repair_private_capture import (
    clear_private_run, configured_private_root, read_private_repair,
)
from czjLLM.job_manager.json_repair_raw_diff_gui import show_private_json_diff


_COLUMNS = (
    ("ts", "觀察時間", 168),
    ("run", "run_id", 180),
    ("item", "工作項目提示碼", 205),
    ("slice", "切片追蹤提示碼", 205),
    ("event", "單次修復事件", 130),
    ("kind", "修復類型（推測）", 156),
    ("chars", "原始→修復字數", 160),
    ("error_pos", "錯誤位置", 94),
    ("literal", "字面值相同率", 120),
    ("keys", "疑似鍵名片段數", 150),
)


def show_json_repair_review(
    parent, stats_provider, case_formatter, summary_formatter, detail_formatter,
):
    """Create one Tk top-level, refreshed only by the owning GUI Tk thread."""
    win = tk.Toplevel(parent)
    win.title("JSON 修復差異檢閱 — 最近案例（只含統計）")
    screen_w = max(760, int(win.winfo_screenwidth()))
    screen_h = max(460, int(win.winfo_screenheight()))
    win.geometry(f"{min(1160, screen_w - 80)}x{min(600, screen_h - 100)}")
    win.minsize(720, 390)
    win.transient(parent)

    heading = ttk.Frame(win, padding=(12, 8))
    heading.pack(fill="x")
    title = ttk.Label(heading, text="JSON 修復前後差異｜最近 12 次觀察",
                      font=("Segoe UI", 12, "bold"))
    title.pack(anchor="w")
    summary = ttk.Label(heading, justify="left", anchor="w")
    summary.pack(anchor="w", fill="x", pady=(5, 0))
    disclaimer = ttk.Label(
        heading, foreground="#9a5800", justify="left",
        text=("新紀錄以工作項目位置＋檔名產生切片追蹤提示碼，TODO／RUNNING 維持相同；"
              "舊紀錄僅有檔名，跨文件可能重複。提示碼並非永久文件 UUID；"
              "單次事件 ID 僅辨識修復次數。統計不保存 JSON 原文，也不證明內容完整。"),
    )
    disclaimer.pack(anchor="w", fill="x", pady=(3, 0))

    def resize_header(event):
        wrap = max(180, int(event.width) - 24)
        summary.configure(wraplength=wrap)
        disclaimer.configure(wraplength=wrap)

    heading.bind("<Configure>", resize_header)

    frame = ttk.Frame(win, padding=(12, 4))
    frame.pack(fill="both", expand=True)
    style_name = "JsonRepairReview.Treeview"
    font = tkfont.nametofont("TkDefaultFont")
    style = ttk.Style(win)
    style.configure(style_name, rowheight=max(27, int(font.metrics("linespace")) + 11))
    style.configure(style_name + ".Heading", font=("Segoe UI", 9, "bold"))
    keys = tuple(x[0] for x in _COLUMNS)
    tree = ttk.Treeview(frame, columns=keys, show="headings",
                        selectmode="browse", height=8, style=style_name)
    for key, label, width in _COLUMNS:
        tree.heading(key, text=label)
        tree.column(key, width=width, minwidth=width, stretch=False,
                    anchor="w" if key in {"ts", "run", "item", "slice", "event", "kind"} else "center")
    vertical = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    horizontal = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    tree.grid(row=0, column=0, sticky="nsew")
    vertical.grid(row=0, column=1, sticky="ns")
    horizontal.grid(row=1, column=0, sticky="ew")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)

    info = ttk.Frame(win, padding=(12, 4))
    info.pack(fill="x")
    detail_label = ttk.Label(info, anchor="w", justify="left", wraplength=600)
    detail_label.pack(fill="x")
    info.bind(
        "<Configure>",
        lambda event: detail_label.configure(
            wraplength=max(180, int(event.width) - 24)
        ),
    )
    graph = tk.Canvas(info, height=75, highlightthickness=0, borderwidth=0)
    graph.pack(fill="x", pady=(4, 2))
    ttk.Label(info, text="藍色＝相同的前／後綴字元　橘色＝中段不同或無法確認（非逐字語意比對）",
              foreground="#555").pack(anchor="w", pady=(0, 4))
    footer = ttk.Frame(win, padding=(12, 4))
    footer.pack(fill="x")
    ttk.Button(footer, text="關閉", command=win.destroy).pack(side="right")
    cases = []

    def _chosen_case():
        selected_rows = tree.selection()
        if not selected_rows:
            return None
        index = int(selected_rows[0])
        return cases[index] if 0 <= index < len(cases) else None

    def _view_private_capture():
        case = _chosen_case()
        directory = configured_private_root()
        if case is None or directory is None:
            messagebox.showinfo(
                "私有原文留存未啟用",
                "沒有選取案例，或尚未設定本機私有快照目錄。"
                "原有品質日誌不儲存 JSON 原文，舊紀錄無法回補。",
                parent=win,
            )
            return
        try:
            pair = read_private_repair(
                directory, case.get("run_id", ""), case.get("event_id", ""),
            )
        except (OSError, ValueError, TypeError, UnicodeError):
            messagebox.showwarning(
                "沒有可驗證的私有原文快照",
                "這筆修復事件沒有可驗證的本機快照。"
                "原文留存預設關閉，請勿用相同切片提示碼猜測來源。",
                parent=win,
            )
            return
        show_private_json_diff(win, pair["original"], pair["repaired"])

    def _clear_private_capture():
        case = _chosen_case()
        directory = configured_private_root()
        if case is None or directory is None:
            messagebox.showinfo("無法清除", "未選取具有 Run ID 的私有快照案例。", parent=win)
            return
        run_id = case.get("run_id", "")
        if not run_id:
            return
        if not messagebox.askyesno(
            "確認清除本次 Run 的私有 JSON 原文",
            "確定清除所選 run_id 對應的所有私有 JSON 修復原文快照？"
            "此操作不可復原，但不會刪除品質日誌、Queue 或 ES 資料。",
            parent=win,
        ):
            return
        try:
            deleted = clear_private_run(
                directory, run_id, "DELETE_PRIVATE_JSON_REPAIRS",
            )
        except (OSError, ValueError, TypeError):
            messagebox.showwarning(
                "私有快照清除未完成", "檔案驗證或刪除失敗；請由本機管理員檢查。",
                parent=win,
            )
            return
        messagebox.showinfo(
            "清除完成", f"已清除本次 Run 的 {deleted} 份私有快照。",
            parent=win,
        )

    ttk.Button(
        footer, text="檢視所選案例原始／修復全文",
        command=_view_private_capture,
    ).pack(side="left")
    ttk.Button(
        footer, text="清除所選 Run 的私有原文",
        command=_clear_private_capture,
    ).pack(side="left", padx=(8, 0))

    def draw_map(case):
        graph.delete("all")
        graph.update_idletasks()
        width = max(550, int(graph.winfo_width() or 800))
        for line, parts, text in (
            (0, change_map_segments(case)[0], "原始"),
            (1, change_map_segments(case)[1], "修復"),
        ):
            y = 6 + line * 34
            graph.create_text(0, y + 10, text=text, anchor="w",
                              fill="#333", font=("Segoe UI", 9))
            total = max(1, sum(parts))
            start, available = 48, max(40, width - 60)
            xpos = start
            for color, amount in (("#3775b5", parts[0]), ("#dc8733", parts[1]),
                                  ("#3775b5", parts[2])):
                if amount <= 0:
                    continue
                segment_w = available * amount / total
                graph.create_rectangle(xpos, y, xpos + segment_w, y + 22,
                                       fill=color, outline="")
                xpos += segment_w

    def selected(_event=None):
        selected_rows = tree.selection()
        if not selected_rows:
            detail_label.configure(
                text="選取案例可查看詞法統計；原文僅能從另外明確啟用的本機私有快照讀取。")
            graph.delete("all")
            return
        index = int(selected_rows[0])
        if 0 <= index < len(cases):
            case = cases[index]
            detail_label.configure(text=detail_formatter(case))
            draw_map(case)

    tree.bind("<<TreeviewSelect>>", selected)
    graph.bind("<Configure>", lambda _event: selected())

    def refresh():
        nonlocal cases
        stats = stats_provider()
        summary.configure(text=summary_formatter(stats))
        unavailable = stats.get("quality_stream_status") in {
            "unverified", "capacity_exceeded",
        }
        next_cases = list((stats.get("repair_analysis_recent") or [])[:12]) if not unavailable else []
        if next_cases == cases:
            return
        prior = tree.selection()
        prior_event = (cases[int(prior[0])].get("event_hint")
                       if prior and int(prior[0]) < len(cases) else None)
        cases = next_cases
        items = tree.get_children()
        if items:
            tree.delete(*items)
        for i, case in enumerate(cases):
            tree.insert("", "end", iid=str(i), values=case_formatter(case))
        target = next(
            (i for i, case in enumerate(cases) if prior_event and
             case.get("event_hint") == prior_event), None
        )
        if target is None and cases:
            target = 0
        if target is not None:
            tree.selection_set(str(target))
            tree.see(str(target))
        selected()

    win.refresh_repair_analysis = refresh
    refresh()
    win.focus_set()
    return win
