# sql_mode/orchestrator.py
#import os, time
import threading, queue
import queue as pyqueue
import tqdm
from typing import Iterable, Tuple, Any
import os, time, faulthandler, sys

import multiprocessing as mp
from czjLLM.job_manager.console_ui import tlog, tlog_ok, tlog_warn
from czjLLM.prompt_pipeline.pipeline_controller import meter_read  # 讀進度計量檔
from czjLLM.prompt_pipeline.pipeline_controller import CONSUMER_STATE  # [ADD] 觀察 last_dispatch_ts
from czjLLM.prompt_pipeline.pipeline_controller import recover_running_to_todo  # ★ 新增：啟動時復原 RUNNING → TODO

from .runtime_ui import prepare_ui, start_bar_refresher
from ..metrics.metering import init_meter
from czjLLM.prompt_pipeline.pipeline_controller import meter_read
try:
    from ..metrics.metering import outstanding_now as _outstanding_now
except Exception:
    _outstanding_now = None

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

def _get_outstanding(meter_fn: str) -> int:
    if callable(_outstanding_now):
        try:
            return int(_outstanding_now(meter_fn))
        except Exception:
            pass
    try:
        m = meter_read(meter_fn)
        q = m.get("queue", {}) or {}
        return int(q.get("pending", 0) or 0) + int(q.get("running", 0) or 0)
    except Exception:
        return 0
    
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
    '''
    mp_log_q = mp_listener_stop = mp_listener = None
    if not DETAIL_CONSUMER_INFO:
        mp_log_q, mp_listener_stop, mp_listener = _start_mp_log_listener()
        #（可選）讓 workers 可以把子程序輸出丟進來
        try:
            ctx.mp_log_q = mp_log_q
        except Exception:
            pass
    '''
    # 3.5) ★ 一次性復原 RUNNING → TODO（在啟動 consumer 前做）
    try:
        items_map = registry.list_items()
        item_dirs = list(items_map.keys())
        recover_running_to_todo(item_dirs)
        tlog("♻️ 已復原上次殘留的 RUNNING 檔案至 TODO。")
    except Exception as ex:
        tlog_warn(f"recover_running_to_todo 失敗：{ex}")
        
    # 4) 佇列與旗標
    done_q = queue.Queue()
    merger_done = threading.Event()

    # === 監控初始化（faulthandler + 停滯偵測）===
    try:
        log_dir = getattr(ctx, "log_dir", os.getcwd())
        os.makedirs(log_dir, exist_ok=True)
        stacks_path = os.path.join(log_dir, "stacks.log")
        # 保持檔案 handle 不被 GC（避免後續寫不到）
        ctx._faulthandler_fp = open(stacks_path, "w", buffering=1, encoding="utf-8")
        faulthandler.enable(file=ctx._faulthandler_fp)
    except Exception as _e:
        # 不中斷主流程
        pass

    def _stall_watchdog(
        meter_path: str,
        stop_ev: threading.Event,
        interval: float = 60.0,
        stall_secs: float = 600.0,
        restart_cb=None,
    ):
        """
        每 interval 秒檢查一次：
          1) 若 outstanding（pending+running）連續 stall_secs 都沒變 → 傾印 stacks（診斷用）
          2) 若 pending>0 且 running==0 並且距離上次派工/回傳結果 >120 秒 → 觸發重啟（restart_cb）
        """
        last_sum = None
        last_change_ts = time.time()
    
        while not stop_ev.is_set():
            try:
                m = meter_read(meter_path)
                q = m.get("queue", {})
                pending = int(q.get("pending", 0) or 0)
                running = int(q.get("running", 0) or 0)
                outstanding = pending + running
    
                # (A) 進度是否卡住很久（總量不變）
                if (last_sum is None) or (outstanding != last_sum):
                    last_sum = outstanding
                    last_change_ts = time.time()
                elif (time.time() - last_change_ts) >= stall_secs:
                    try:
                        msg = f"[watchdog] 進度 {int(stall_secs)} 秒無前進（outstanding={outstanding}），正在傾印 thread dump 至 stacks.log"
                        print(msg)
                    except Exception:
                        pass
                    try:
                        faulthandler.dump_traceback(file=getattr(sys.modules[__name__], "ctx", None) and getattr(sys.modules[__name__].ctx, "_faulthandler_fp", None) or sys.stderr)
                    except Exception:
                        pass
                    last_change_ts = time.time()  # 重設避免洗版
    
                # (B) pool/consumer 疑似卡死：有待處理、卻沒有在跑，而且很久沒派工/回傳
                long_no_dispatch = (time.monotonic() - float(CONSUMER_STATE.get("last_dispatch_ts", 0.0))) > 120.0
                if (pending > 0) and (running == 0) and long_no_dispatch:
                    tlog_warn("🧯 [watchdog] 檢測到 pending>0 且 running==0，且 120s 無派工/結果 → 嘗試重啟 consumer")
                    if callable(restart_cb):
                        try:
                            restart_cb()
                            tlog_warn("🔄 [watchdog] 已呼叫 restart_cb()")
                            # 重置基準，給新一輪一些緩衝時間
                            last_sum = None
                            last_change_ts = time.time()
                        except Exception as re:
                            tlog_warn(f"⚠️ restart_cb 失敗：{re}")
                            
                stale_run = (running > 0) and ((time.monotonic() - float(CONSUMER_STATE.get("last_dispatch_ts", 0.0))) > 300.0)
                if stale_run:
                    tlog_warn("🧯 [watchdog] running>0 且 300s 無派工/回傳 → 嘗試重啟 consumer")
                    if callable(restart_cb):
                        try:
                            restart_cb()
                            tlog_warn("🔄 [watchdog] 已針對 running>0 case 重新啟動 consumer")
                            last_sum = None
                            last_change_ts = time.time()
                        except Exception as re:
                            tlog_warn(f"⚠️ restart_cb 失敗：{re}")
    
            except Exception:
                pass
            time.sleep(interval)
    # 於 worker 啟動後建立 watchdog
    stop_event, consumer, merger = start_workers(ctx, registry, meter_fn, is_sqlite, done_q, sink=sink)

    #try:
    #    th_watchdog = threading.Thread(target=_stall_watchdog, args=(meter_fn, stop_event), daemon=True)
    #    th_watchdog.start()
    #except Exception:
    #    pass

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

    # [ADD] 可重啟的包裝：關閉舊 consumer/merger/drain + 換一顆新的 stop_event 再啟動
    def _try_restart_consumer_pool():
        nonlocal stop_event, consumer, merger, drain
    
        tlog_warn("🛑 正在關閉舊 consumer/merger/drain ...")
        try:
            stop_event.set()
        except Exception:
            pass
    
        # 給一點時間讓舊執行緒收尾
        for th, name in [(consumer, "consumer"), (merger, "merger"), (drain, "drain")]:
            try:
                if th and th.is_alive():
                    th.join(timeout=5.0)
            except Exception:
                pass
    
        # 建立新的 stop_event 與 workers
        tlog_warn("🚀 重建新的 worker 與事件 ...")
        stop_event, consumer, merger = start_workers(ctx, registry, meter_fn, is_sqlite, done_q, sink=sink)
    
        # 重啟 drain（沿用同一個 done_q / p_done）
        try:
            drain = threading.Thread(
                target=progress_drain,
                args=(stop_event, done_q, p_done, getattr(ctx, "gui_handle", None)),
                kwargs={"close_event": merger_done},
                daemon=True
            )
            drain.start()
            tlog_warn(f"[drain] restarted={drain.is_alive()}")
        except Exception as de:
            tlog_warn(f"⚠️ 重啟 drain 失敗：{de}")
    try:
        th_watchdog = threading.Thread(
            target=_stall_watchdog,
            args=(meter_fn, stop_event),
            kwargs=dict(interval=60.0, stall_secs=600.0, restart_cb=_try_restart_consumer_pool),
            daemon=True
        )
        th_watchdog.start()
    except Exception:
        pass
    
    # 7) 防雜訊：條形圖自動 refresh
    refresher, bar_refresh_stop = start_bar_refresher(p_sched, p_done, interval=0.15)

    # 8) 主回圈：排程所有列（改成執行緒，主線程負責收尾條件）
    producer_done_flag = threading.Event()

    def _producer_main():
        try:
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
                p_done=p_done,   # 空字串時補完成條
            )
        finally:
            producer_done_flag.set()

    prod_th = threading.Thread(target=_producer_main, daemon=True, name="producer-thread")
    prod_th.start()

    # 8.5) 完成條件守門：A+B+C+D 皆為 True 才能進入收尾
    total_rows = len(rows_for_count)
    last_report = 0.0

    def _registry_empty() -> bool:
        try:
            return len(registry.list_items() or {}) == 0
        except Exception:
            return False

    while True:
        A = producer_done_flag.is_set()                         # 產生端已跑完
        B = (_get_outstanding(meter_fn) <= 0)                  # 無未完成（pending+running）
        C = _registry_empty()                                  # registry 清空
        D = (getattr(p_done, "n", 0) >= int(total_rows or 0))  # 完成條達到總列數（含空字串補點）

        now = time.time()
        if (now - last_report) > 5.0:
            tlog(f"[watch] prod_done={A}, out={_get_outstanding(meter_fn)}, "
                 f"reg_empty={C}, done={getattr(p_done, 'n', 0)}/{total_rows}")
            last_report = now

        if A and B and C and D:
            break
        time.sleep(0.2)

    # 9) 收尾清理（四條件皆真才宣布完成）
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

    tlog_ok("🎉 資料處理完成！")