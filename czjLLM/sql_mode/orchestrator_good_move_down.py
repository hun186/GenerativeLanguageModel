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

'''TO REMOVE
# ---------------------------
# 小工具：條形圖自動 refresh 守護緒
# ---------------------------
def _start_bar_refresher(p_sched, p_done, interval=0.15):
    stop_ev = threading.Event()
    def _bar_refresher():
        while not stop_ev.is_set():
            try:
                p_sched.refresh()
                p_done.refresh()
            except Exception:
                pass
            time.sleep(interval)
    th = threading.Thread(target=_bar_refresher, daemon=True)
    th.start()
    return th, stop_ev


# ---------------------------
# 小工具：統一消費 done_q → 推進完成進度（Console/GUI）
# 退出條件：close_event 已 set 且佇列為空
# ---------------------------
def _progress_drain(stop_event, done_q, p_done, gui=None, close_event=None):
    import queue as pyqueue
    try:
        try:
            tlog("[drain] loop started")
        except Exception:
            pass

        while True:
            try:
                _ = done_q.get(timeout=0.2)
                try:
                    p_done.update(1)
                except Exception:
                    pass
                if gui:
                    try:
                        gui.inc_done(1)
                    except Exception:
                        pass
                done_q.task_done()
            except pyqueue.Empty:
                if (close_event is not None and close_event.is_set()) and done_q.empty():
                    break
            time.sleep(0.01)
    except Exception as ex:
        try:
            tlog_warn(f"[drain] 例外：{ex}")
        except Exception:
            pass
    finally:
        try:
            tlog("[drain] loop exited")
        except Exception:
            pass


# ---------------------------
# UI 準備（Windows GUI + Console 進度條）
# ---------------------------
def _prepare_ui(ctx, total_rows: int):
    gui = try_start_gui(total=total_rows, title="LLM 分析進度（Windows GUI）")
    gui_sink = None
    if gui:
        gui_sink = make_gui_sink(gui)
        add_log_sink(gui_sink)
        ctx.gui_handle = gui
        ctx.gui_sink = gui_sink

    p_sched, p_done, restore_console = setup_console_ui(total_rows)
    return gui, gui_sink, p_sched, p_done, restore_console


# ---------------------------
# 計量器初始化（meter 檔、門檻）
# ---------------------------
def _init_meter(ctx):
    registry = ItemsRegistry()
    meter_fn = meter_path_init(ctx)
    thresholds = meter_init(
        meter_fn, ctx,
        low=getattr(ctx, "load_low_watermark", None),
        high=getattr(ctx, "load_high_watermark", None)
    )
    low  = thresholds["thresholds"]["low"]
    high = thresholds["thresholds"]["high"]
    return registry, meter_fn, low, high


# ---------------------------
# 啟動 worker threads（consumer + merger）
# ---------------------------
def _start_workers(ctx, registry, meter_fn, is_sqlite, done_q):
    stop_event = threading.Event()

    consumer = threading.Thread(
        target=llm_stream_consumer,
        args=(ctx, registry, meter_fn, stop_event, is_sqlite),
        kwargs={"per_round_limit": getattr(ctx, "per_round_limit", 128)},
        daemon=True
    )
    consumer.start()

    merger = threading.Thread(
        target=row_merger_watchdog,
        args=(ctx, registry, meter_fn, stop_event, is_sqlite),
        kwargs={"scan_interval": 0.2, "done_q": done_q},
        daemon=True
    )
    merger.start()

    return stop_event, consumer, merger


# ---------------------------
# 主回圈：排程所有列並處理背壓
# ---------------------------
def _produce_rows(ctx, rows_for_count, registry, meter_fn, low, high, stop_event, consumer, p_sched, gui):
    def outstanding_now():
        m = meter_read(meter_fn)
        return m["queue"]["pending"] + m["queue"]["running"]

    for idx, (pk, text) in enumerate(rows_for_count):
        if not text:
            p_sched.update(1)
            if gui: gui.inc_sched(1)
            # 完成條的 +1 交由 watchdog + drain 負責
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

        while outstanding_now() > low:
            time.sleep(0.05)


# ---------------------------
# 收尾：停止 worker、等待 drain、關閉 UI/日志
# ---------------------------
def _shutdown(ctx, gui, gui_sink, restore_console,
              stop_event, consumer, merger,
              drain, merger_done,
              refresher, bar_refresh_stop):
    # 停掉生產/消費
    stop_event.set()
    consumer.join()
    merger.join()
    merger_done.set()

    # 停掉 drain
    if drain.is_alive():
        drain.join(timeout=2.0)

    # 停掉 bar refresher
    bar_refresh_stop.set()
    if refresher.is_alive():
        refresher.join(timeout=1.0)

    # 關 GUI 日誌 sink / GUI / 還原 console
    try:
        if gui_sink: remove_log_sink(gui_sink)
    except Exception:
        pass
    try:
        if gui: gui.close()
    except Exception:
        pass
    try:
        restore_console()
    except Exception:
        pass

    # ★★★ 停掉 MP 日誌 listener
    try:
        mp_log_q = getattr(ctx, "mp_log_q", None)
        mp_listener = getattr(ctx, "mp_listener", None)  # 若你想存起來也可
    except Exception:
        mp_log_q = None
        mp_listener = None
'''
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