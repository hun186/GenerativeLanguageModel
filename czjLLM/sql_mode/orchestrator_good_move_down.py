# sql_mode/orchestrator.py
#import os, time
import threading, queue
import queue as pyqueue
import tqdm
from typing import Iterable, Tuple, Any

import multiprocessing as mp
#from prompt_pipeline.pipeline_controller import (
#    ItemsRegistry, meter_path_init, meter_init, meter_read, meter_update,
#    llm_stream_consumer, row_merger_watchdog, find_item_dir_for, producer_backpressure_wait
#)
#from utilities.file_utils import save_text_as_temp_file
#from utils.utilities_path import getMFNFromFN, OSWALK
from job_manager.console_ui import tlog, tlog_ok
#from job_manager.win_gui import try_start_gui, make_gui_sink
#from job_manager.console_ui import add_log_sink, remove_log_sink

from .runtime.runtime_ui import prepare_ui, start_bar_refresher
from .metrics.metering import init_meter
from .runtime.mp_logs import start_mp_log_listener, stop_mp_log_listener
from .runtime.workers import start_workers, progress_drain#, outstanding_now
#from .runtime.scheduler import schedule_one_row
from .runtime.teardown import shutdown
from .runtime.producer import produce_rows
'''
def schedule_one_row(ctx, registry, meter_fn, idx: int, pk: Any, text: str):
    from handlers.handle_txt_file import handle_single_input_file  # 延用現有函式
    temp_txt_path = save_text_as_temp_file(text, ctx.llm_source_dir, idx)
    handle_single_input_file(
        temp_txt_path, ctx, adjust=True,
        pause_seconds=(10 if idx == 0 else 0),
        defer_merge=True
    )

    main_file_name = getMFNFromFN(temp_txt_path)
    item_dir = find_item_dir_for(ctx, main_file_name)
    todo_dir = os.path.join(item_dir, "TODO")
    total_chunks = len(OSWALK(todo_dir))
    registry.add(item_dir, pk, temp_txt_path)

    def _on_add_row(d):
        d["rows"].setdefault(pk, {
            "item_dir": item_dir,
            "temp_txt": temp_txt_path,
            "total": 0, "done": 0, "status": "in_progress"
        })
        d["rows"][pk]["total"] = total_chunks
        d["queue"]["pending"] += total_chunks
    meter_update(meter_fn, _on_add_row)
    return total_chunks
'''          


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
def run_pipeline(ctx, pending_iter: Iterable[Tuple[Any, str]], is_sqlite: bool):
    # 1) 取資料筆數（可改為估算節省記憶體）
    rows_for_count = list(pending_iter)
    processable = len(rows_for_count)

    # 2) UI 準備
    #gui, gui_sink, p_sched, p_done, restore_console = _prepare_ui(ctx, processable)
    gui, gui_sink, p_sched, p_done, restore_console = prepare_ui(ctx, processable)
    
    # 3) 計量器就緒
    #registry, meter_fn, low, high = _init_meter(ctx)
    registry, meter_fn, low, high = init_meter(ctx)

    # 4) 佇列與旗標
    done_q = queue.Queue()
    merger_done = threading.Event()

    # ★★★ 新增：啟動 MP 日誌 listener，並把 Queue 放到 ctx，供子程序 initializer 使用
    mp_log_q, mp_listener_stop, mp_listener = _start_mp_log_listener()
    #mp_log_q, mp_listener_stop, mp_listener = start_mp_log_listener() #fail
    ctx.mp_log_q = mp_log_q
    
    # 5) 啟動 workers
    #stop_event, consumer, merger = _start_workers(ctx, registry, meter_fn, is_sqlite, done_q)
    stop_event, consumer, merger = start_workers(ctx, registry, meter_fn, is_sqlite, done_q)

    # 6) 進度 drain（以 merger_done 控制退出）
    gui_handle = getattr(ctx, "gui_handle", None)
    drain = threading.Thread(
        #target=_progress_drain,
        target=progress_drain,
        args=(stop_event, done_q, p_done, gui_handle),
        kwargs={"close_event": merger_done},
        daemon=True
    )
    drain.start()
    tlog(f"[drain] started={drain.is_alive()}")

    # 7) 防雜訊：條形圖自動 refresh
    #refresher, bar_refresh_stop = _start_bar_refresher(p_sched, p_done, interval=0.15)
    refresher, bar_refresh_stop = start_bar_refresher(p_sched, p_done, interval=0.15)

    # 8) 主回圈：排程所有列
    #_produce_rows(ctx, rows_for_count, registry, meter_fn, low, high, stop_event, consumer, p_sched, gui)
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
    '''
    for idx, (pk, text) in enumerate(rows_for_count):
        if not text:
            p_sched.update(1)
            if gui: gui.inc_sched(1)
            # 完成條 +1 交給 watchdog + drain
            continue

        producer_backpressure_wait(
            ctx=ctx,
            low=low, meter_fn=meter_fn, stop_event=stop_event,
            consumer_thread=consumer, registry=registry,
            soft_timeout=getattr(ctx, "bp_soft_timeout", 30.0),
            hard_timeout=getattr(ctx, "bp_hard_timeout", 120.0),
            sleep_step=0.05
        )

        schedule_one_row(ctx, registry, meter_fn, idx, pk, text)
        p_sched.update(1)
        if gui: gui.inc_sched(1)

        while outstanding_now(meter_fn) > low:
            time.sleep(0.05)
    '''
    # 9) 收尾清理
    
    #_shutdown(ctx, gui, gui_sink, restore_console,
    #          stop_event, consumer, merger,
    #          drain, merger_done,
    #          refresher, bar_refresh_stop)
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
    _stop_mp_log_listener(mp_log_q, mp_listener_stop, mp_listener)
    
    tlog_ok("🎉 資料處理完成！")