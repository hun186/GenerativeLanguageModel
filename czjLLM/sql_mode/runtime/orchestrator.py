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
from czjLLM.prompt_pipeline.pipeline_controller import start_watchdogs
from czjLLM.utilities.combine_utils import run_merge_for
from czjLLM.utilities.slice_merge import should_merge_slices

from .runtime_ui import prepare_ui, start_bar_refresher
from ..metrics.metering import init_meter
try:
    from ..metrics.metering import outstanding_now as _outstanding_now
except Exception:
    _outstanding_now = None

from .mp_logs import start_mp_log_listener, stop_mp_log_listener
from .workers import start_workers, progress_drain
from .workers import consumer_restart_cb

from .teardown import finalize_gui, shutdown
from .producer import produce_rows
from .pending_recheck import (
    emit_pending_recheck_completion_summary,
    recheck_scheduled_after_writeback,
)

from .sinks.sql_sink import SqlSink
from .sinks.excel_sink import ExcelSink
from czjLLM.reduction.production_control import (
    ensure_execution_cancel_event, ensure_production_observer,
    execution_cancel_requested, finish_legacy_merge_item,
    legacy_merge_item_completed, legacy_merge_item_materialized,
    request_execution_cancel, try_begin_legacy_merge_item,
)
from czjLLM.reduction.retention import (
    parse_reduction_retention_policy,
    prompt_container_retention_root,
    run_reduction_retention,
)



    
DETAIL_CONSUMER_INFO = True

def make_sink(ctx, is_sqlite):
    mode = getattr(ctx, "mode", "")
    if mode == "table":                        # Excel/CSV 模式
        # 需要 ctx.output_excel_file 已在前面 workflow 設定好
        main_sheet = getattr(ctx, "target_sheet_name", None) or "LLM_result"
        return ExcelSink(ctx, main_path=ctx.output_excel_file,main_sheet=main_sheet)
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

def _is_reg_drained(reg) -> bool:
    """寬鬆定義：無 pending、無 running 視為 drained。沒有 stats() 則退回 empty()。"""
    try:
        st = reg.stats()  # 期待 {'pending':..,'running':..,'finished':..,'dispatched':..}
        return st.get('pending', 0) == 0 and st.get('running', 0) == 0
    except Exception:
        try:
            if hasattr(reg, "empty"):
                return bool(reg.empty())
        except Exception:
            pass
        try:
            items = reg.list_items() if hasattr(reg, "list_items") else {}
            return len(items or {}) == 0
        except Exception:
            # 保守：無法判斷時視為尚未 drained，避免過早收尾/錯誤觀測。
            return False


def _dir_file_count(p: str) -> int:
    try:
        c = 0
        for _, _, files in os.walk(p):
            c += len(files)
        return c
    except Exception:
        return 0

# ====== 新增：讀計量檔與掃描 FS 的輔助 ======

def _read_meter_counts(meter_fn: str) -> dict:
    """從計量檔讀 queue 計數，安全容錯。"""
    try:
        m = meter_read(meter_fn)
        q = m.get("queue", {}) or {}
        return {
            "pending":   int(q.get("pending",   0) or 0),
            "running":   int(q.get("running",   0) or 0),
            "completed": int(q.get("completed", 0) or 0),
        }
    except Exception:
        return {"pending": 0, "running": 0, "completed": 0}


def _fs_totals(job_dirs: Iterable[str]) -> dict:
    """彙總所有 job_dir 的 TODO/RUNNING/Success 檔案數。"""
    totals = {"TODO": 0, "RUNNING": 0, "Success": 0}
    for d in job_dirs:
        totals["TODO"]    += _dir_file_count(os.path.join(d, "TODO"))
        totals["RUNNING"] += _dir_file_count(os.path.join(d, "RUNNING"))
        totals["Success"] += _dir_file_count(os.path.join(d, "Success"))
    return totals


def _fs_running_top(job_dirs: Iterable[str], top_n: int = 5) -> list[tuple[str, int]]:
    """回傳 RUNNING 檔案數最多的前 N 個 item 目錄（[(dir, running_count), ...]）。"""
    ranks = []
    for d in job_dirs:
        cnt = _dir_file_count(os.path.join(d, "RUNNING"))
        if cnt > 0:
            ranks.append((d, cnt))
    ranks.sort(key=lambda x: x[1], reverse=True)
    return ranks[:top_n]
    
def _can_combine(d: str) -> bool:
    todo_cnt    = _dir_file_count(os.path.join(d, "TODO"))
    run_cnt     = _dir_file_count(os.path.join(d, "RUNNING"))
    success_cnt = _dir_file_count(os.path.join(d, "Success"))
    return success_cnt > 0 and todo_cnt == 0 and run_cnt == 0


def _fallback_merge_enabled(ctx) -> bool:
    """Keep the post-drain fallback gate identical to execution semantics."""
    return should_merge_slices(ctx)


def _registry_item_present(registry, job_dir: str) -> bool:
    getter = getattr(registry, "get", None)
    if callable(getter):
        try:
            return getter(job_dir) is not None
        except Exception:
            pass
    lister = getattr(registry, "list_items", None)
    if callable(lister):
        try:
            return job_dir in (lister() or {})
        except Exception:
            pass
    # Conservative fallback: unknown registry visibility means keep handoff.
    return True


def _registry_existing_combined_artifact(registry, job_dir: str) -> str:
    """Return the live row's authoritative combined artifact when it exists."""
    meta = None
    getter = getattr(registry, "get", None)
    if callable(getter):
        try:
            meta = getter(job_dir)
        except Exception:
            meta = None
    if meta is None:
        lister = getattr(registry, "list_items", None)
        if callable(lister):
            try:
                meta = (lister() or {}).get(job_dir)
            except Exception:
                meta = None
    if not isinstance(meta, dict):
        return ""
    path = str(meta.get("CombBackFN", "") or "")
    return path if path and os.path.isfile(path) else ""

# ===========================
# 對外主函式：run_pipeline（精簡後）
# ===========================
def run_pipeline(ctx, pending_iter: Iterable[Tuple[Any, str]], is_sqlite: bool, sink=None):
    # 1) 取資料筆數（可改為估算節省記憶體）
    rows_for_count = list(pending_iter)
    processable = len(rows_for_count)
    producer_stop_event = ensure_execution_cancel_event(ctx)
    observer = ensure_production_observer(ctx)

    # 2) UI 準備
    gui, gui_sink, p_sched, p_done, restore_console = prepare_ui(ctx, processable)
    # The observer is created before the GUI. Publish once now so the fixed
    # status section immediately shows the actual activity mode instead of 0/0.
    observer.publish_snapshot(force=True)
    
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
    try:
        fs0 = _fs_totals(item_dirs)
        tlog(f"📦 初始檔案狀態 fs(TODO/RUN/Succ)={fs0.get('TODO',0)}/{fs0.get('RUNNING',0)}/{fs0.get('Success',0)}")
    except Exception:
        pass
        
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

    '''
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
    '''
    # 於 worker 啟動後建立 watchdog
    stop_event, consumer, merger = start_workers(ctx, registry, meter_fn, is_sqlite, done_q, sink=sink)
    # Operator cancellation stops only producer scheduling.  Worker stop_event
    # remains the teardown signal owned by start_workers()/shutdown().
    start_watchdogs(
        ctx,
        adapter=getattr(ctx, "_es_adapter", None),
        ping_interval_sec=60,
        stall_idle_threshold_sec=600,
        stall_interval_sec=60,
        stacks_path=None,
        meter_fn=meter_fn,
        restart_cb=lambda: consumer_restart_cb(ctx),  # 只發訊號，不要重建 thread
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
    merged_jobs = set()   # 已合併
    seen_job_dirs = set() # 曾出現過（後備用）

    # 7) 防雜訊：條形圖自動 refresh
    refresher, bar_refresh_stop = start_bar_refresher(p_sched, p_done, interval=0.15)

    # 8) 主回圈：排程所有列（改成執行緒，主線程負責收尾條件）
    producer_done_flag = threading.Event()
    producer_result = {"scheduled": 0}

    def _producer_main():
        try:
            producer_result["scheduled"] = produce_rows(
                ctx=ctx,
                rows_for_count=rows_for_count,
                registry=registry,
                meter_fn=meter_fn,
                low=low,
                #stop_event=stop_event,
                stop_event=producer_stop_event,
                consumer=consumer,
                p_sched=p_sched,
                gui=gui,
                p_done=p_done,   # 空字串時補完成條
            )
            ctx._producer_actual_scheduled_rows = producer_result["scheduled"]
        finally:
            producer_done_flag.set()

    prod_th = threading.Thread(target=_producer_main, daemon=True, name="producer-thread")
    prod_th.start()
    # ---- 合併設定：與實際 slice-merge execution 使用同一 canonical predicate ----
    MERGE_SLICES = _fallback_merge_enabled(ctx)
    # 8.5) 完成條件守門：A+B+C+D 皆為 True 才能進入收尾
    total_rows = len(rows_for_count)
    last_report = 0.0

    def _registry_empty() -> bool:
        try:
            return len(registry.list_items() or {}) == 0
        except Exception:
            return False

    while True:
        if gui is not None and callable(getattr(gui, "cancellation_requested", None)):
            if gui.cancellation_requested():
                request_execution_cancel(ctx, source="gui")
        out_now = _get_outstanding(meter_fn)
        A = producer_done_flag.is_set()          # 產生端已跑完
        B = (out_now <= 0)                      # 無未完成（pending+running）
        C = False                               # 先別急著用舊的 registry 清空判斷，下面會放寬
        D = (getattr(p_done, "n", 0) >= int(total_rows or 0))  # 完成條達到總列數（含空字串補點）

        # 以「寬鬆」規則判斷 registry 狀態（drained = 無 pending & 無 running）
        reg_drained = _is_reg_drained(registry)

        # 讀取（若有）全域統計：finished/dispatched/running
        try:
            st = registry.stats()
            finished   = st.get('finished', 0)
            dispatched = st.get('dispatched', 0)
            running    = st.get('running', 0)
        except Exception:
            finished = dispatched = 0
            running  = 0

        # 累積所有看過的 job_dir，避免 registry 被清空後找不到要合併的目錄
        try:
            cur_items = registry.list_items() or {}
            for _d in cur_items.keys():
                seen_job_dirs.add(_d)
        except Exception:
            pass

        # 放寬的「可觸發合併」條件
        should_merge = A and B and (reg_drained or (finished >= dispatched and running == 0))

        # 觸發合併（可能有多個 job_dir，就逐一處理）
        if should_merge and MERGE_SLICES:
            try:
                if hasattr(registry, 'compact'):
                    registry.compact()
            except Exception:
                pass
        
            try:
                items_map = registry.list_items() or {}
                job_dirs = list(items_map.keys())
            except Exception:
                job_dirs = []
        
            # 目前 + 曾看過 的候選
            candidates = (set(job_dirs) | seen_job_dirs) - merged_jobs
            if execution_cancel_requested(ctx):
                candidates = set()
        
            for job_dir in sorted(candidates):
                # Scheduler/multistage may already have produced the
                # authoritative row artifact and published it to the registry.
                # Never let the post-drain fallback overwrite that handoff.
                if _registry_existing_combined_artifact(registry, job_dir):
                    merged_jobs.add(job_dir)
                    continue
                if not _can_combine(job_dir):
                    continue
                if not try_begin_legacy_merge_item(ctx, job_dir):
                    if legacy_merge_item_completed(ctx, job_dir):
                        merged_jobs.add(job_dir)
                    # If another path merely owns the active claim, leave this
                    # candidate retryable in case that attempt later fails.
                    continue
                observer.emit("legacy_merge_started", {})
                try:
                    merged_ok = run_merge_for(
                        ctx, job_dir, registry=registry
                    )  # fallback 成功時必須把實際 CombBackFN handoff 給仍存活的 registry row
                    if merged_ok is not False:
                        # run_merge_for only materializes/publishes the artifact.
                        # Row Merger owns semantic slice-merge completion while
                        # the registry row remains live. If another successful
                        # writeback path already removed the row during fallback,
                        # no Row Merger remains to adopt the materialized claim:
                        # release ownership and close this fallback attempt as
                        # superseded by the already-completed writeback.
                        if (
                            not _registry_item_present(registry, job_dir)
                            and legacy_merge_item_materialized(ctx, job_dir)
                        ):
                            finish_legacy_merge_item(ctx, job_dir, success=False)
                            observer.emit(
                                "legacy_merge_completed",
                                {"reason": "writeback_already_completed"},
                            )
                            tlog(f"🧩 fallback 合併已被既有成功寫回取代：{job_dir}")
                        else:
                            tlog(f"🧩 已產生切片合併素材，等待 Row Merger 完成語意合併：{job_dir}")
                        merged_jobs.add(job_dir)
                    else:
                        finish_legacy_merge_item(ctx, job_dir, success=False)
                        observer.emit("legacy_merge_failed", {"reason": "no_output"})
                except Exception as e:
                    finish_legacy_merge_item(ctx, job_dir, success=False)
                    observer.emit(
                        "legacy_merge_failed",
                        {"error_type": type(e).__name__, "reason": "execution_error"},
                    )
                    tlog_warn(f"合併失敗（{job_dir}）：{e}")

        # 更新 C（若 registry 真的乾淨，就當作清空）
        C = reg_drained
        '''
        # 報表（每 5 秒）
        now = time.time()
        if (now - last_report) > 5.0:
            tlog(f"[watch] prod_done={A}, out={out_now}, reg_empty={C}, done={getattr(p_done, 'n', 0)}/{total_rows}")
            last_report = now
        '''
        # 報表（每 5 秒）
        now = time.time()
        if (now - last_report) > 5.0:
            # 取得目前可觀察的 job_dir：當前 registry + 曾看過
            try:
                items_map = registry.list_items() or {}
                job_dirs_now = set(items_map.keys()) | seen_job_dirs
            except Exception:
                job_dirs_now = set(seen_job_dirs)
        
            # 計量檔（queue）與檔案系統（目錄檔數）雙軌度量
            q_counts = _read_meter_counts(meter_fn)                 # {'pending','running','completed'}
            fs_counts = _fs_totals(job_dirs_now)                    # {'TODO','RUNNING','Success'}
        
            # 主行：把重點塞在一行，直覺可視
            tlog(
                "[watch] prod_done=%s | "
                "queue(pend/run/comp)=%d/%d/%d | "
                "fs(TODO/RUN/Succ)=%d/%d/%d | "
                "reg_empty=%s | "
                "done=%d/%d"
                % (
                    A,
                    q_counts["pending"], q_counts["running"], q_counts["completed"],
                    fs_counts["TODO"], fs_counts["RUNNING"], fs_counts["Success"],
                    C,
                    getattr(p_done, "n", 0), int(total_rows or 0),
                )
            )
        
            # 加值：每 30 秒列出 RUNNING 檔最多的前幾個目錄，幫助快速定位熱點
            if int(now) % 30 < 5:
                hot = _fs_running_top(job_dirs_now, top_n=5)
                if hot:
                    # 精簡輸出：每個目錄取尾段名 + 數量
                    brief = []
                    for d, cnt in hot:
                        name = os.path.basename(os.path.normpath(d))
                        brief.append(f"{name}:{cnt}")
                    tlog("  ↳ RUNNING top: " + ", ".join(brief))
        
            last_report = now
        # 放寬退出條件：
        # - 一般情境：仍優先依 p_done（D）判斷完成列數
        # - 多階段/特殊寫回：有時 done_q 不會回補 p_done，會導致 D 卡住在 0
        #   此時若 producer 已完成、queue 已清空、registry 已 drained（或 finished>=dispatched 且 running=0）
        #   即可視為已完成，避免主流程無限等待。
        progress_done_or_drained = D or (C and B)
        exit_ok = A and B and progress_done_or_drained and (C or (finished >= dispatched and running == 0))

        if exit_ok:
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
        close_gui=False,
    )

    completion = recheck_scheduled_after_writeback(ctx)
    emit_pending_recheck_completion_summary(
        ctx,
        total_rows=total_rows,
        scheduled_rows=producer_result["scheduled"],
        done_rows=getattr(p_done, "n", None),
    )
    # A request observed before authoritative post-writeback classification
    # makes the run cancelled even when producer traversal had just finished.
    # Requests made after this terminal transition cannot retroactively change it.
    cancelled = execution_cancel_requested(ctx)
    if cancelled:
        ctx.run_status = "cancelled"
        observer.emit("run_cancelled", {"attempted": processable,
                      "succeeded": producer_result["scheduled"],
                      "failed": max(0, processable - producer_result["scheduled"]),
                      "stop_reason": "cancelled"})
    elif completion["pending"] or completion["errors"]:
        ctx.run_status = "failed"
        observer.emit("run_failed", {"reason": "incomplete_writeback"})
        tlog_warn(
            "⚠️ 資料處理流程已結束，但寫回完成後重查仍有 "
            f"pending={completion['pending']}, errors={completion['errors']}；請勿視為全部完成。"
        )
    else:
        ctx.run_status = "completed"
        observer.emit("run_completed", {"attempted": processable,
                      "succeeded": producer_result["scheduled"], "failed": 0})
        tlog_ok("🎉 資料處理完成！")
    reduction_stats = observer.snapshot()
    summary = (
        "Reduction execution summary: "
        f"candidate rows={processable}, scheduled={producer_result['scheduled']}, "
        f"completed={getattr(p_done, 'n', 0)}, run status={ctx.run_status}, "
        f"stages completed={reduction_stats['stages_completed']}, "
        f"members attempted={reduction_stats['members_attempted']}, "
        f"members failed={reduction_stats['members_failed']}, "
        f"partial accepted={reduction_stats['partial_accepted']}"
    )
    if ctx.run_status == "cancelled":
        summary += "; new scheduling cancelled, in-flight work safely drained; subset may be processed"
    if ctx.run_status == "completed":
        tlog(summary)
    else:
        tlog_warn(summary)
    # Bounded maintenance runs only after authoritative writeback classification
    # and worker shutdown.  It is never allowed to change the user run result.
    try:
        raw_retention = getattr(ctx, "reduction_retention", None)
        if raw_retention is None and isinstance(getattr(ctx, "cfg", None), dict):
            raw_retention = ctx.cfg.get("reduction_retention")
        retention_policy = parse_reduction_retention_policy(raw_retention)
        prompt_root = getattr(ctx, "prompt_dir", None)
        if retention_policy.enabled and prompt_root:
            run_reduction_retention(
                [prompt_container_retention_root(prompt_root)],
                retention_policy,
                observer=observer,
            )
    except Exception as retention_error:
        observer.emit(
            "reduction_retention_failed",
            {"error_type": type(retention_error).__name__},
        )
        tlog_warn("⚠️ Reduction retention maintenance failed; persisted results remain successful.")
    finalize_gui(gui=gui, gui_sink=gui_sink)
    return producer_result["scheduled"]
