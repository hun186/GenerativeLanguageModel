# sql_mode/orchestrator.py
#import os, time
import threading, queue
import queue as pyqueue
import tqdm
from typing import Iterable, Tuple, Any

import multiprocessing as mp
from czjLLM.job_manager.console_ui import tlog, tlog_ok

from .runtime_ui import prepare_ui, start_bar_refresher
from ..metrics.metering import init_meter
from .mp_logs import start_mp_log_listener, stop_mp_log_listener
from .workers import start_workers, progress_drain
from .teardown import shutdown
from .producer import produce_rows

from .sinks.sql_sink import SqlSink
from .sinks.excel_sink import ExcelSink

DETAIL_CONSUMER_INFO = True

def make_sink(ctx, is_sqlite):
    mode = getattr(ctx, "mode", "")
    if mode == "table":                        # Excel/CSV 模式
        # 需要 ctx.output_excel_file 已在前面 workflow 設定好
        return ExcelSink(ctx, main_path=ctx.output_excel_file,main_sheet = "LLM_result")
    else:                                      # 預設 SQL
        return SqlSink(ctx, is_sqlite=is_sqlite)
    

#==========模組化run_pipeline

def _start_mp_log_listener():
    """啟動子程序 stdout/stderr 轉發器，回傳 (q, stop_ev, thread)。"""
    #import multiprocessing as mp
    import threading
    q = mp.Queue()
    stop_ev = threading.Event()

    def _mp_log_listener(q_, stop_):
        #import queue as pyqueue
        while not stop_.is_set():
            try:
                line = q_.get(timeout=0.2)
            except pyqueue.Empty:
                continue
            try:
                # 用 tqdm.write 不會破壞進度條
                #from tqdm import tqdm
                tqdm.write(str(line))
            except Exception:
                pass

    th = threading.Thread(target=_mp_log_listener, args=(q, stop_ev), daemon=True)
    th.start()
    return q, stop_ev, th

def _stop_mp_log_listener(q, stop_ev, th):
    """安全停止 listener。"""
    try:
        stop_ev.set()
    except Exception:
        pass
    try:
        if th.is_alive():
            th.join(timeout=1.0)
    except Exception:
        pass
    # 嘗試關閉 Queue（不同平台支援度不同，能關就關）
    try:
        q.cancel_join_thread()
    except Exception:
        pass
    try:
        q.close()
    except Exception:
        pass

# ===========================
# 對外主函式：run_pipeline（精簡後）
# ===========================
def run_pipeline(ctx, pending_iter: Iterable[Tuple[Any, str]], is_sqlite: bool, sink=None):
    # 1) 取資料筆數（可改為估算節省記憶體）
    rows_for_count = list(pending_iter)
    processable = len(rows_for_count)

    # 2) UI 準備
    gui, gui_sink, p_sched, p_done, restore_console = prepare_ui(ctx, processable)
    
    # 3) 計量器就緒
    registry, meter_fn, low, high = init_meter(ctx)

    # 4) 佇列與旗標
    done_q = queue.Queue()
    merger_done = threading.Event()

    # ★★★ 新增：啟動 MP 日誌 listener，並把 Queue 放到 ctx，供子程序 initializer 使用
    if not DETAIL_CONSUMER_INFO:
        #mp_log_q, mp_listener_stop, mp_listener = _start_mp_log_listener()
        mp_log_q, mp_listener_stop, mp_listener = start_mp_log_listener() #may fail
        ctx.mp_log_q = mp_log_q
    
    
    # 5) 啟動 workers
    #sink = make_sink(ctx, is_sqlite)

    stop_event, consumer, merger = start_workers(
        #ctx, registry, meter_fn, is_sqlite, done_q
        ctx, registry, meter_fn, is_sqlite, done_q, sink=sink
        )

    # 6) 進度 drain（以 merger_done 控制退出）
    gui_handle = getattr(ctx, "gui_handle", None)
    drain = threading.Thread(
        target=progress_drain,
        args=(stop_event, done_q, p_done, gui_handle),
        kwargs={"close_event": merger_done},
        daemon=True
    )
    drain.start()
    tlog(f"[drain] started={drain.is_alive()}")

    # 7) 防雜訊：條形圖自動 refresh
    refresher, bar_refresh_stop = start_bar_refresher(p_sched, p_done, interval=0.15)

    # 8) 主回圈：排程所有列
    produce_rows(
        ctx=ctx,
        rows_for_count=rows_for_count,
        registry=registry,
        meter_fn=meter_fn,
        low=low,
        stop_event=stop_event,
        consumer=consumer,
        p_sched=p_sched,
        gui=gui,
        p_done=p_done,   # ← 可選；要在空字串時補完成條就傳入
    )

    # 9) 收尾清理

    shutdown(
        ctx,
        gui=gui,
        gui_sink=gui_sink,
        restore_console=restore_console,
        stop_event=stop_event,
        consumer=consumer,
        merger=merger,
        drain=drain,
        merger_done=merger_done,
        refresher=refresher,
        bar_refresh_stop=bar_refresh_stop,
    )
    if not DETAIL_CONSUMER_INFO:
        _stop_mp_log_listener(mp_log_q, mp_listener_stop, mp_listener)
    
    tlog_ok("🎉 資料處理完成！")