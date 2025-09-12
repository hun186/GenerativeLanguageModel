# czjLLM/job_manager/win_gui.py
import sys
import multiprocessing as mp
import queue as pyqueue
from dataclasses import dataclass

# 僅 Windows 啟用 GUI；其他平台回傳 None
IS_WIN = (sys.platform == "win32")

@dataclass
class _GuiEvents:
    INC_SCHED: str = "inc_sched"
    INC_DONE:  str = "inc_done"
    LOG:       str = "log"
    CLOSE:     str = "close"
    SET_TOTAL: str = "set_total"

# ---------- 子行程：Tk 主迴圈 ----------

def _enable_windows_dpi_awareness():
    if not IS_WIN:
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        # Windows 10優先 PER_MONITOR_AWARE_V2(-4) → (-3) → (-2)
        for ctx in (-4, -3, -2):
            try:
                if hasattr(user32, "SetProcessDpiAwarenessContext"):
                    if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(ctx)):
                        return
            except Exception:
                pass
        # 8.1 備援
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            return
        except Exception:
            pass
        # 最後備援
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass
    except Exception:
        pass

def _gui_proc_main(q: "mp.Queue", total: int, title: str):
    """子行程內執行：所有 Tk 操作都在這裡，避免跨緒/跨行程錯誤。"""
    _enable_windows_dpi_awareness()
    try:
        import tkinter as tk
        from tkinter import ttk
        import tkinter.font as tkfont
        import time
    except Exception:
        # 無法載入 Tk，直接吃掉隊列直到 CLOSE
        while True:
            try:
                evt, _ = q.get(timeout=0.5)
                if evt == _GuiEvents.CLOSE:
                    break
            except pyqueue.Empty:
                pass
        return

    root = tk.Tk()
    root.title(title or "LLM 分析進度")
    root.geometry("760x500")  # 高度略增，容納 ETA 區塊

    # DPI-aware scaling
    try:
        dpi = float(root.winfo_fpixels("1i"))
        root.tk.call("tk", "scaling", max(1.0, dpi / 72.0))
    except Exception:
        pass

    # 字型調整：Segoe UI / Consolas
    try:
        for name, size in [
            ("TkDefaultFont", 10),
            ("TkTextFont",    10),
            ("TkFixedFont",   10),
            ("TkMenuFont",    10),
            ("TkHeadingFont", 11),
        ]:
            try:
                f = tkfont.nametofont(name)
                if name == "TkFixedFont":
                    f.configure(family="Consolas", size=size)
                else:
                    f.configure(family="Segoe UI", size=size)
            except Exception:
                pass
        style = ttk.Style()
        style.configure(".", font=("Segoe UI", 10))
    except Exception:
        pass

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill="both", expand=True)

    # 內部狀態
    _tot = max(1, int(total))
    _done_cnt  = 0
    _sched_cnt = 0

    # ---- ETA 估算狀態（指數平滑，降低抖動）----
    _t0 = None            # 開始時間（第一次排程/完成時啟動）
    _last_ts = None       # 上次完成事件時間
    _last_done = 0        # 上次完成數
    _rate_ema = 0.0       # 平滑後速率（列/秒）
    _ALPHA = 0.25         # 平滑係數（越大越敏感）

    def _fmt(n: int) -> str:
        return f"{n:,}"

    def _pct(n: int, d: int) -> str:
        return f"{(n/d*100):.0f}%" if d > 0 else "0%"

    def _fmt_dur(sec: float | None) -> str:
        if sec is None:
            return "—"
        sec = max(0, int(sec))
        h = sec // 3600
        m = (sec % 3600) // 60
        s = sec % 60
        return f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

    def _maybe_boot_timer():
        nonlocal _t0, _last_ts
        if _t0 is None:
            _t0 = _last_ts = time.time()

    def _accumulate_rate(on_inc_done: int):
        """完成事件時更新速率 EMA。"""
        nonlocal _last_ts, _last_done, _rate_ema
        now = time.time()
        if _last_ts is None:
            _last_ts = now
            _last_done = _done_cnt - on_inc_done
        dt = max(1e-6, now - _last_ts)
        ddone = max(0, (_done_cnt - _last_done))
        inst_rate = ddone / dt if ddone > 0 else 0.0
        if inst_rate > 0:
            _rate_ema = inst_rate if _rate_ema <= 0 else (1 - _ALPHA) * _rate_ema + _ALPHA * inst_rate
            _last_ts = now
            _last_done = _done_cnt

    def _eta_text():
        if _t0 is None:
            return "⏱ 已用時 00:00｜剩餘 —｜預計完成 —｜速度 — 列/秒"
        now = time.time()
        elapsed = now - _t0
        if _rate_ema > 0.0:
            remain = (_tot - _done_cnt) / _rate_ema
            finish_ts = now + remain
            finish_str = time.strftime("%H:%M:%S", time.localtime(finish_ts))
            rate_str = f"{_rate_ema:.2f} 列/秒"
        else:
            remain = None
            finish_str = "—"
            rate_str = "—"
        return f"⏱ 已用時 {_fmt_dur(elapsed)}｜剩餘 {_fmt_dur(remain)}｜預計完成 {finish_str}｜速度 {rate_str}"

    def _update_labels():
        lbl_sched.configure(text=f"排程進度（切片／入佇列） {_fmt(_sched_cnt)}/{_fmt(_tot)}  ({_pct(_sched_cnt, _tot)})")
        lbl_done.configure(text=f"完成進度（合併＋寫回）  {_fmt(_done_cnt)}/{_fmt(_tot)}  ({_pct(_done_cnt, _tot)})")
        lbl_eta.configure(text=_eta_text())

    lbl_sched = ttk.Label(frm)
    bar_sched = ttk.Progressbar(frm, maximum=_tot, value=0, length=680)

    lbl_done  = ttk.Label(frm)
    bar_done  = ttk.Progressbar(frm, maximum=_tot, value=0, length=680)

    lbl_sched.pack(anchor="w"); bar_sched.pack(fill="x", pady=(0,8))
    lbl_done.pack(anchor="w");  bar_done.pack(fill="x", pady=(0,8))

    # ---- ETA 顯示（新增）----
    lbl_eta = ttk.Label(frm, foreground="#555")
    lbl_eta.pack(anchor="w", pady=(0, 8))

    _update_labels()

    txt = tk.Text(frm, height=15, wrap="word")
    scr = ttk.Scrollbar(frm, command=txt.yview)
    txt.configure(yscrollcommand=scr.set, font=("Consolas", 10), bg="white", fg="black",
                  insertbackground="black", spacing1=2, spacing2=1, spacing3=2)
    txt.pack(side="left", fill="both", expand=True)
    scr.pack(side="right", fill="y")

    def append(msg: str):
        if not msg:
            return
        txt.insert("end", msg.rstrip() + "\n")
        txt.see("end")

    def set_total(v: int):
        nonlocal _tot
        _tot = max(1, int(v))
        bar_done.configure(maximum=_tot)
        bar_sched.configure(maximum=_tot)
        bar_done["value"]  = min(bar_done["value"],  _tot)
        bar_sched["value"] = min(bar_sched["value"], _tot)
        _update_labels()

    def _shutdown():
        try:
            root.quit()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass

    root.protocol("WM_DELETE_WINDOW", _shutdown)

    # 事件輪詢：全部在 Tk 主緒
    def poll():
        nonlocal _tot, _done_cnt, _sched_cnt
        try:
            updated = False
            while True:
                evt, payload = q.get_nowait()
                if evt == _GuiEvents.INC_SCHED:
                    _maybe_boot_timer()
                    inc = int(payload or 1)
                    _sched_cnt = min(_sched_cnt + inc, _tot)
                    bar_sched["value"] = _sched_cnt
                    updated = True
                elif evt == _GuiEvents.INC_DONE:
                    _maybe_boot_timer()
                    inc = int(payload or 1)
                    _done_cnt = min(_done_cnt + inc, _tot)
                    bar_done["value"] = _done_cnt
                    _accumulate_rate(inc)
                    updated = True
                elif evt == _GuiEvents.LOG:
                    append(str(payload))
                elif evt == _GuiEvents.SET_TOTAL:
                    set_total(int(payload)); updated = True
                elif evt == _GuiEvents.CLOSE:
                    _shutdown(); return
        except pyqueue.Empty:
            pass

        if updated or _t0 is not None:
            _update_labels()

        root.after(200, poll)  # 200ms 更新一次即可

    root.after(100, poll)
    try:
        root.mainloop()
    except Exception:
        pass


# ---------- 主行程：薄客戶端（丟訊息而已） ----------

class _GUIClient:
    def __init__(self, q: "mp.Queue", proc: "mp.Process"):
        self._q = q
        self._proc = proc

    def inc_sched(self, n: int = 1): self._q.put((_GuiEvents.INC_SCHED, n))
    def inc_done(self,  n: int = 1): self._q.put((_GuiEvents.INC_DONE,  n))
    def log(self, text: str):        self._q.put((_GuiEvents.LOG, text))
    def set_total(self, total: int): self._q.put((_GuiEvents.SET_TOTAL, int(total)))

    def close(self):
        try:
            self._q.put((_GuiEvents.CLOSE, None))
        except Exception:
            pass
        if self._proc.is_alive():
            self._proc.join(timeout=5.0)

# 對外：Windows 才啟動 GUI；失敗則回 None（不影響主流程）
def try_start_gui(total: int, title: str = "LLM 分析進度（Windows GUI）"):
    if not IS_WIN:
        return None
    try:
        ctx = mp.get_context("spawn")  # Windows 安全模式
        q = ctx.Queue()
        p = ctx.Process(target=_gui_proc_main, args=(q, int(total), title), daemon=False)
        p.start()
        return _GUIClient(q, p)
    except Exception as ex:
        #print(ex)
        return None

# 提供 sink：把 console/log 訊息同步到 GUI（仍建議用在 Windows）
def make_gui_sink(gui: _GUIClient):
    def sink(level: str, message: str):
        try:
            prefix = {"ERROR": "[ERR] ", "WARN": "[WARN] ", "OK": "[OK] ", "INFO": ""}.get(level, "")
            gui.log(prefix + message)
        except Exception:
            pass
    return sink
