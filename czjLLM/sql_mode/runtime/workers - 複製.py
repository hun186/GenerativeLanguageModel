# sql_mode/workers.py
import threading, time
from prompt_pipeline.pipeline_controller import llm_stream_consumer, row_merger_watchdog, meter_read
from job_manager.console_ui import tlog, tlog_warn
from ..utils.term_lock import TQDM_LOCK

def start_workers(ctx, registry, meter_fn, is_sqlite, done_q):
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