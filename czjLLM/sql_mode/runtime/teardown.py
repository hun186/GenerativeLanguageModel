# sql_mode/runtime/teardown.py
from ...job_manager.console_ui import remove_log_sink


def finalize_gui(*, gui, gui_sink) -> None:
    """Close GUI after its authoritative terminal snapshot has been queued."""
    try:
        if gui_sink:
            remove_log_sink(gui_sink)
    except Exception:
        pass
    try:
        if gui:
            gui.close()
    except Exception:
        pass


def shutdown(
    ctx,
    gui,
    gui_sink,
    restore_console,
    stop_event,
    consumer,
    merger,
    drain,
    merger_done,
    refresher,
    bar_refresh_stop,
    close_gui=True,
):
    """
    收尾所有前景/背景資源（不含 MP 日誌 listener；那個由呼叫端負責 stop）。
    """
    # 1) 通知 worker 停止
    try:
        stop_event.set()
    except Exception:
        pass

    # 2) 等待 worker 結束
    try:
        if consumer and consumer.is_alive():
            consumer.join()
    except Exception:
        pass

    try:
        if merger and merger.is_alive():
            merger.join()
    except Exception:
        pass

    # 3) 告訴 drain：合併已完成，可以在佇列清空時退出
    try:
        merger_done.set()
    except Exception:
        pass

    # 4) 停 drain（若仍在）
    try:
        if drain and drain.is_alive():
            drain.join(timeout=2.0)
    except Exception:
        pass

    # 5) 停條形圖 refresher
    try:
        bar_refresh_stop.set()
    except Exception:
        pass
    try:
        if refresher and refresher.is_alive():
            refresher.join(timeout=1.0)
    except Exception:
        pass

    # 6) 移除 GUI sink、關 GUI、還原 console
    if close_gui:
        finalize_gui(gui=gui, gui_sink=gui_sink)

    try:
        if restore_console:
            restore_console()
    except Exception:
        pass
