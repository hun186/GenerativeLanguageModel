# sql_mode/workers.py
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

    consumer = threading.Thread(
        target=llm_stream_consumer,
        args=(ctx, registry, meter_fn, stop_event, is_sqlite),
        kwargs={"per_round_limit": getattr(ctx, "per_round_limit", 128)},
        daemon=True,
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

def start_workers_OLD(ctx, registry, meter_fn, is_sqlite, done_q, sink=None):
    stop_event = threading.Event()

    consumer = threading.Thread(
        target=llm_stream_consumer,
        args=(ctx, registry, meter_fn, stop_event, is_sqlite),
        kwargs={"per_round_limit": getattr(ctx, "per_round_limit", 128)},
        daemon=True
    )
    consumer.start()

    #sink = SqlSink(ctx, is_sqlite=is_sqlite)
    '''
    merger = threading.Thread(
        target=row_merger_watchdog,
        args=(ctx, registry, meter_fn, stop_event, is_sqlite),
        kwargs={"scan_interval": 0.2, "done_q": done_q},
        daemon=True
    )
    '''
    '''
    merger = threading.Thread(
        target=row_merger_watchdog_generic,
        args=(ctx, registry, meter_fn, stop_event, sink),
        kwargs={"scan_interval": 0.2, "done_q": done_q},
        daemon=True
    )
    '''
    
    # 根據 mode 決定 sink：SQL 或 Excel
    if getattr(ctx, "mode", "") == "table":
        sink = ExcelSink(ctx, input_path=ctx.input_excel_file,output_path=ctx.output_excel_file,main_sheet = "LLM_result")
    elif getattr(ctx, "mode", "") == "sql":
        sink = SqlSink(ctx, is_sqlite=is_sqlite)
    else:
        print(f'Fail to define the sink for the mode {getattr(ctx, "mode", "")}!')
        raise Exception

    merger = threading.Thread(
        target=row_merger_watchdog_generic,
        args=(ctx, registry, meter_fn, stop_event, sink),
        kwargs={"scan_interval": 0.2, "done_q": done_q},
        daemon=True,
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