# sql_mode/runtime/workers.py
import threading, time
from czjLLM.prompt_pipeline.pipeline_controller import llm_stream_consumer,meter_read
from czjLLM.job_manager.console_ui import tlog, tlog_warn
from ..utils.term_lock import TQDM_LOCK

from .row_merger_generic import row_merger_watchdog_generic
from .sinks.sql_sink import SqlSink
from .sinks.excel_sink import ExcelSink
#from .sinks.csv_sink import CSVSink
#from tabular_mode.runtime.sinks.csv_sink import CSVSink  # 你的 CSVSink

#def start_workers(ctx, registry, meter_fn, is_sqlite, done_q):
def start_workers(ctx, registry, meter_fn, is_sqlite, done_q, sink=None):
    """
    啟動 consumer 與 row-merger 兩個工作執行緒。
    - sink 必須由外層（handle_data_mode / backend.make_sink）建立並傳入
    - 不要在這裡再根據 mode 決定 sink，避免覆蓋外層選擇
    """
    if sink is None:
        # 強烈建議直接丟錯，迫使外層按新流程傳入 sink
        raise ValueError(
            "start_workers 需要外部提供 sink（請在 handle_data_mode 的 backend.make_sink 建立並傳入）。"
        )

    stop_event = threading.Event()

    # ★ 新增：專用「重啟 consumer」事件（不要用 stop_event）
    restart_event = threading.Event()
    ctx._consumer_restart_ev = restart_event  # 提供給 watchdog 的 restart_cb 使用
    
    consumer = threading.Thread(
        target=llm_stream_consumer,

        #args=(ctx, registry, meter_fn, stop_event, restart_event, is_sqlite),
        #kwargs={"per_round_limit": getattr(ctx, "per_round_limit", 128),
        #        "restart_event": restart_event},
        
        # 只到 stop_event 為止：4 個位置參數
        args=(ctx, registry, meter_fn, stop_event),
        # 其餘都用 kwargs 傳，不要重複
        kwargs=dict(
            restart_event=restart_event,
            is_sqlite=is_sqlite,
            per_round_limit=getattr(ctx, "per_round_limit", 128),
        ),
        daemon=True,
        name="consumer-thread",
    )
    consumer.start()

    merger = threading.Thread(
        target=row_merger_watchdog_generic,
        args=(ctx, registry, meter_fn, stop_event, sink),
        kwargs={"scan_interval": 0.2, "done_q": done_q},
        daemon=True,
    )
    merger.start()

    return stop_event, consumer, merger

def consumer_restart_cb(ctx):
    ev = getattr(ctx, "_consumer_restart_ev", None)
    # 先確認有 set() 方法；若有 is_set() 則避免重複 set 與重複日誌
    if hasattr(ev, "set"):
        try:
            already = getattr(ev, "is_set", lambda: False)()
        except Exception:
            already = False
        if not already:
            ev.set()
            try:
                tlog_warn("[restart_cb] 已送出 consumer 熱重啟信號（不觸碰 stop_event）")
            except Exception:
                pass
                
# 只送出 consumer 熱重啟信號（不動 stop_event / 不重建 thread）
def consumer_restart_cb_old_1030(ctx):
    ev = getattr(ctx, "_consumer_restart_ev", None)
    if isinstance(ev, threading.Event) and not ev.is_set():
        ev.set()
        tlog_warn("[restart_cb] 已送出 consumer 熱重啟信號（不觸碰 stop_event）")
        
def consumer_restart_cb_old_1030(ctx):
    ev = getattr(ctx, "_consumer_restart_ev", None)
    if not isinstance(ev, threading.Event):
        tlog_warn("[restart_cb] 無法取得重啟事件（_consumer_restart_ev）")
        return
    # 防抖：避免短時間連續重啟
    now = time.monotonic()
    if (now - getattr(ctx, "_last_consumer_restart_ts", 0.0)) < 30.0:
        tlog_warn("[restart_cb] 距上次重啟 <30s，略過")
        return
    setattr(ctx, "_last_consumer_restart_ts", now)
    ev.set()
    tlog_warn("[restart_cb] 已送出 consumer 熱重啟信號（不觸碰 stop_event）")
    
def consumer_restart_cb_old(ctx):
    ev = getattr(ctx, "_consumer_restart_ev", None)
    if isinstance(ev, threading.Event):
        now = time.monotonic()
        last = getattr(ctx, "_last_consumer_restart_ts", 0.0)
        if (now - last) < 30.0:  # 防抖：30 秒內不重複重啟
            tlog_warn("[restart_cb] 距前次重啟 <30s，略過。")
            return
        setattr(ctx, "_last_consumer_restart_ts", now)
        ev.set()
        tlog_warn("[restart_cb] 已送出 consumer 重啟訊號")
    else:
        tlog_warn("[restart_cb] ctx._consumer_restart_ev 不存在，無法重啟")


def progress_drain(stop_event, done_q, p_done, gui=None, close_event=None):
    """消費 done_q，同步 Console 與 GUI 完成進度。"""
    import queue as pyqueue
    try: tlog("[drain] loop started")
    except Exception: pass

    try:
        while True:
            try:
                _ = done_q.get(timeout=0.2)
                try:
                    with TQDM_LOCK:
                        p_done.update(1)
                except Exception:
                    pass
                if gui:
                    try: gui.inc_done(1)
                    except Exception: pass
                done_q.task_done()
            except pyqueue.Empty:
                if (close_event is not None and close_event.is_set()) and done_q.empty():
                    break
            time.sleep(0.01)
    except Exception as ex:
        try: tlog_warn(f"[drain] 例外：{ex}")
        except Exception: pass
    finally:
        try: tlog("[drain] loop exited")
        except Exception: pass

def outstanding_now(meter_fn: str) -> int:
    m = meter_read(meter_fn)
    return m["queue"]["pending"] + m["queue"]["running"]