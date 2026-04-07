import time, threading, queue
from typing import Iterable, Tuple, Any

from job_manager.console_ui import tlog, tlog_ok, tlog_warn, remove_log_sink
from job_manager.console_ui import add_log_sink  # 若你要動態掛/卸 GUI sink
from prompt_pipeline.pipeline_controller import producer_backpressure_wait
from .runtime_ui import prepare_ui, start_bar_refresher
from ..metrics.metering import init_meter
from .scheduler import schedule_one_row
from .workers import start_workers, progress_drain, outstanding_now
from .mp_logs import start_mp_log_listener, stop_mp_log_listener

def run_pipeline(ctx, pending_iter: Iterable[Tuple[Any, str]], is_sqlite: bool):
    # 1) 取資料筆數（可改為估算節省記憶體）
    rows_for_count = list(pending_iter)
    processable = len(rows_for_count)

    # 2) UI 準備
    gui, gui_sink, p_sched, p_done, restore_console = prepare_ui(ctx, processable)

    # 3) 計量器就緒
    registry, meter_fn, low, high = init_meter(ctx)
    ctx._meter_fn = meter_fn  # ★ 釘在 ctx，給所有執行緒/子模組參考
    print("meter_fn in run_pipeline",meter_fn)

    # 4) 佇列與旗標
    done_q = queue.Queue()
    merger_done = threading.Event()

    # 5) 啟動 MP 日誌 listener（給子程序）
    mp_log_q, mp_listener_stop, mp_listener = start_mp_log_listener()
    ctx.mp_log_q = mp_log_q

    # 6) 啟動 consumer / merger
    stop_event, consumer, merger = start_workers(ctx, registry, meter_fn, is_sqlite, done_q)

    # 7) 進度 drain（以 merger_done 控制退出）
    gui_handle = getattr(ctx, "gui_handle", None)
    drain = threading.Thread(
        target=progress_drain,
        args=(stop_event, done_q, p_done, gui_handle),
        kwargs={"close_event": merger_done},
        daemon=True
    )
    drain.start()
    tlog(f"[drain] started={drain.is_alive()}")

    # 8) 防雜訊：條形圖自動 refresh（如不需要可關）
    refresher, bar_refresh_stop = start_bar_refresher(p_sched, p_done, interval=0.15)

    # 9) 主回圈：排程所有列 + 背壓
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

    # 10) 收尾清理
    stop_event.set()
    consumer.join()
    merger.join()
    merger_done.set()

    if drain.is_alive():
        drain.join(timeout=2.0)

    bar_refresh_stop.set()
    if refresher.is_alive():
        refresher.join(timeout=1.0)

    # 卸 GUI sink、關 GUI、還原 console
    try:
        if gui_sink: remove_log_sink(gui_sink)
    except Exception: pass
    try:
        if gui: gui.close()
    except Exception: pass
    try:
        restore_console()
    except Exception: pass

    # 停 listener
    stop_mp_log_listener(mp_log_q, mp_listener_stop, mp_listener)

    tlog_ok("🎉 資料處理完成！")