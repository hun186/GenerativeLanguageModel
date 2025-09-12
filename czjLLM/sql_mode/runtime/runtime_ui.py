import threading, time
from job_manager.win_gui import try_start_gui, make_gui_sink
from job_manager.console_ui import setup_console_ui, add_log_sink
from ..utils.term_lock import TQDM_LOCK

def prepare_ui(ctx, total_rows: int):
    """建立 Win GUI（如可）+ Console 進度條，並回傳 GUI 句柄與還原函式。"""
    gui = try_start_gui(total=total_rows, title="LLM 分析進度（Windows GUI）")
    gui_sink = None
    if gui:
        gui_sink = make_gui_sink(gui)
        add_log_sink(gui_sink)
        ctx.gui_handle = gui
        ctx.gui_sink = gui_sink

    p_sched, p_done, restore_console = setup_console_ui(total_rows)
    return gui, gui_sink, p_sched, p_done, restore_console

def start_bar_refresher(p_sched, p_done, interval=0.15):
    """定期 refresh 兩條 bar，搭配 TQDM_LOCK 避免被雜訊覆蓋。"""
    stop_ev = threading.Event()
    def _ref():
        while not stop_ev.is_set():
            try:
                with TQDM_LOCK:
                    p_sched.refresh()
                    p_done.refresh()
                #p_sched.refresh()
                #p_done.refresh()
            except Exception:
                pass
            time.sleep(interval)
    th = threading.Thread(target=_ref, daemon=True)
    th.start()
    return th, stop_ev