# -*- coding: utf-8 -*-
"""View an explicitly selected, already-authorized private JSON repair pair.

The caller must supply exact in-memory strings from the run/event-linked
private capture reader. No persistence, network, logging or source inference.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk


def _common_segments(before: str, after: str) -> tuple[int, int]:
    n = min(len(before), len(after))
    prefix = 0
    while prefix < n and before[prefix] == after[prefix]:
        prefix += 1
    suffix = 0
    while (suffix < n - prefix and before[len(before)-1-suffix]
           == after[len(after)-1-suffix]):
        suffix += 1
    return prefix, suffix


def show_private_json_diff(owner, original: str, repaired: str):
    """Side-by-side exact character views, bounded by private reader limits."""
    win = tk.Toplevel(owner)
    win.title("私有 JSON 修復前後原文｜僅供本機檢視")
    sw = max(850, int(win.winfo_screenwidth()))
    sh = max(520, int(win.winfo_screenheight()))
    win.geometry(f"{min(1200, sw - 80)}x{min(720, sh - 110)}")
    win.minsize(760, 430)
    win.transient(owner)

    prefix, suffix = _common_segments(original, repaired)
    ttk.Label(
        win, text=("橘色區段＝字元發生變化或未確認相同；綠色＝共同前／後綴。"
                   " 這不是語意或來源完整性驗證。"),
        padding=(10, 8),
    ).pack(fill="x")
    panel = ttk.Frame(win, padding=(10, 0))
    panel.pack(fill="both", expand=True)
    panel.columnconfigure(0, weight=1, uniform="raw")
    panel.columnconfigure(1, weight=1, uniform="raw")
    panel.rowconfigure(1, weight=1)

    widgets = []
    for index, (title, content) in enumerate(
        (("原始 JSON（解析失敗）", original), ("修復後 JSON（已可解析）", repaired))
    ):
        ttk.Label(panel, text=f"{title}｜{len(content):,} 字元").grid(
            row=0, column=index, sticky="w", padx=(0, 6), pady=(0, 4),
        )
        frame = ttk.Frame(panel)
        frame.grid(row=1, column=index, sticky="nsew", padx=(0, 6))
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        # Never publish a highlighted confidential selection through X11
        # PRIMARY merely because the user dragged across the raw text.
        txt = tk.Text(frame, wrap="none", font=("Consolas", 10),
                      undo=False, exportselection=False,
                      relief="sunken", borderwidth=1)
        scroll_y = ttk.Scrollbar(frame, orient="vertical", command=txt.yview)
        scroll_x = ttk.Scrollbar(frame, orient="horizontal", command=txt.xview)
        txt.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        txt.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        txt.insert("1.0", content)
        txt.tag_configure("same", background="#e8f5e9")
        txt.tag_configure("changed", background="#ffe1b2")
        a, b = len(content), max(0, len(content) - suffix)
        txt.tag_add("same", "1.0", f"1.0+{prefix}c")
        txt.tag_add("changed", f"1.0+{prefix}c", f"1.0+{b}c")
        if suffix:
            txt.tag_add("same", f"1.0+{b}c", f"1.0+{a}c")
        txt.configure(state="disabled")
        widgets.append(txt)

    footer = ttk.Frame(win, padding=10)
    footer.pack(fill="x")

    def jump_to_change():
        for widget in widgets:
            index = f"1.0+{prefix}c"
            widget.see(index)
            widget.mark_set("insert", index)

    ttk.Label(
        footer,
        text=(f"相同前綴 {prefix:,} 字／相同後綴 {suffix:,} 字；"
              "只在明確選取案例時將原文載入記憶體。"),
    ).pack(side="left")
    ttk.Button(footer, text="跳到首處差異",
               command=jump_to_change).pack(side="right", padx=(8, 0))
    ttk.Button(footer, text="關閉", command=win.destroy).pack(side="right")
    jump_to_change()
    win.focus_set()
    return win
