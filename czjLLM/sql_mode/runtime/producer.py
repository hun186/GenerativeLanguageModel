# sql_mode/runtime/producer.py
import time
from typing import Iterable, Tuple, Any, Optional

from czjLLM.job_manager.console_ui import tlog_warn,tlog
from czjLLM.prompt_pipeline.pipeline_controller import producer_backpressure_wait
from czjLLM.prompt_pipeline.pipeline_controller import meter_update
from .workers import outstanding_now
from .scheduler import schedule_one_row


def _still_pending_before_dispatch(ctx, pk: Any) -> bool:
    """Recheck remote SQL/ES state immediately before slicing/dispatching a row.

    Scheduled runs can overlap.  The initial pending iterator may have selected a
    row that another main process finishes before this producer reaches it.
    Returning False skips slicing and parallel dispatch for that stale row.
    """
    adapter = getattr(ctx, "_pending_adapter", None)
    if adapter is None or not hasattr(adapter, "is_row_pending"):
        return True

    if not getattr(ctx, "_pending_recheck_announced", False):
        source_kind = adapter.__class__.__name__
        tlog(
            "[producer] pending recheck 啟用：每列切片/派工前會再次查詢遠端 SQL/ES 狀態；"
            f"若 pk 已完成會略過。adapter={source_kind}"
        )
        try:
            setattr(ctx, "_pending_recheck_announced", True)
        except Exception:
            pass

    output_cols = getattr(ctx, "output_cols", None) or [getattr(ctx, "output_col", "")]
    try:
        is_pending = bool(adapter.is_row_pending(
            tgt_table=getattr(ctx, "_pending_tgt_table", getattr(ctx, "target_table", None)),
            pk=getattr(ctx, "primary_key", ""),
            pk_value=pk,
            output_cols=output_cols,
        ))
        if getattr(ctx, "debug_pending_recheck", False):
            state = "pending" if is_pending else "already_completed"
            tlog(f"[producer] pending recheck pk={pk} state={state}")
        return is_pending
    except Exception as e:
        tlog_warn(f"[producer] pending recheck 失敗 pk={pk}: {e!r}；保守繼續排程。")
        return True


def produce_rows(
    ctx,
    rows_for_count: Iterable[Tuple[Any, str]],
    registry,
    meter_fn: str,
    low: int,
    stop_event,
    consumer,
    p_sched,
    gui=None,
    p_done: Optional[object] = None,   # 若傳入，遇到空字串時幫忙把完成條 +1
):
    """
    逐列排程，處理背壓，並在收尾時等待所有外送工作完成。
    回傳實際成功排程的列數。
    """
    scheduled = 0
    seen = 0
    try:
        total_rows = len(rows_for_count)  # 若是 list 可取得，generator 會丟 TypeError
    except TypeError:
        total_rows = None

    if total_rows is not None:
        tlog(f"[producer] will iterate {total_rows} rows")

    for idx, row in enumerate(rows_for_count):
        if len(row) >= 3:
            pk, text, source_inputs = row[0], row[1], row[2]
        else:
            pk, text = row[0], row[1]
            source_inputs = None
        seen += 1

        if stop_event.is_set():
            tlog_warn("produce_rows: stop_event set，提前結束排程。")
            # ★新增：提前結束也要回報目前游標；不要把 prod_done 設 True
            try:
                meter_update(meter_fn, lambda d: d.setdefault("progress", {}).update({
                    "cursor": seen, "enq": scheduled, "producer_alive": False,
                    "last_progress_ts": time.time(), "prod_done": False
                }))
            except Exception:
                pass
            break

        if not text:
            try: p_sched.update(1)
            except Exception: pass
            if gui:
                try: gui.inc_sched(1)
                except Exception: pass
            if p_done is not None:
                try: p_done.update(1)
                except Exception: pass
                if gui:
                    try: gui.inc_done(1)
                    except Exception: pass
            # ★新增：空列也更新游標，避免 watchdog 判定「長時間無進度」
            try:
                meter_update(meter_fn, lambda d: d.setdefault("progress", {}).update({
                    "cursor": seen, "enq": scheduled, "producer_alive": True,
                    "last_progress_ts": time.time()
                }))
            except Exception:
                pass
            continue

        try:
            producer_backpressure_wait(
                ctx=ctx, low=low, meter_fn=meter_fn, stop_event=stop_event,
                consumer_thread=consumer, registry=registry,
                soft_timeout=getattr(ctx, "bp_soft_timeout", 30.0),
                hard_timeout=getattr(ctx, "bp_hard_timeout", 120.0),
                sleep_step=0.05,
            )
        except Exception as e:
            tlog_warn(f"[producer] backpressure wait 例外，略過此列 pk={pk}: {e!r}")
            try:
                meter_update(meter_fn, lambda d: d.setdefault("progress", {}).update({
                    "cursor": seen, "enq": scheduled, "producer_alive": True,
                    "last_progress_ts": time.time(),
                    "last_error": f"backpressure:{type(e).__name__}"
                }))
            except Exception:
                pass
            continue

        try:
            if not _still_pending_before_dispatch(ctx, pk):
                tlog(f"[producer] pk={pk} 已由其他程序完成，略過本次切片/派工。")
                try: p_sched.update(1)
                except Exception: pass
                if gui:
                    try: gui.inc_sched(1)
                    except Exception: pass
                if p_done is not None:
                    try: p_done.update(1)
                    except Exception: pass
                    if gui:
                        try: gui.inc_done(1)
                        except Exception: pass
                try:
                    meter_update(meter_fn, lambda d: d.setdefault("progress", {}).update({
                        "cursor": seen, "enq": scheduled, "producer_alive": True,
                        "last_progress_ts": time.time(), "last_skip_reason": "already_completed"
                    }))
                except Exception:
                    pass
                continue

            schedule_one_row(ctx, registry, meter_fn, idx, pk, text, source_inputs=source_inputs)
            scheduled += 1
            # ★新增：每送一列即回報游標/送件數
            try:
                meter_update(meter_fn, lambda d: d.setdefault("progress", {}).update({
                    "cursor": seen, "enq": scheduled, "producer_alive": True,
                    "last_progress_ts": time.time()
                }))
            except Exception:
                pass
        except Exception as e:
            tlog_warn(f"[producer] schedule_one_row 失敗 pk={pk}: {e!r}")
            continue

        

        try: p_sched.update(1)
        except Exception: pass
        if gui:
            try: gui.inc_sched(1)
            except Exception: pass

        while not stop_event.is_set() and outstanding_now(meter_fn) > low:
            time.sleep(0.05)

    # ===== 收尾等待 =====
    soft = getattr(ctx, "producer_drain_soft", 30.0)
    hard = getattr(ctx, "producer_drain_hard", 600.0)
    start = time.time()
    last_out = None

    while True:
        out = outstanding_now(meter_fn)
        if out <= 0:
            break
        now = time.time()
        if last_out != out and (now - start) > soft:
            tlog_warn(f"[producer] 等待 outstanding 歸零中… outstanding={out}")
            last_out = out
        if (now - start) > hard:
            tlog_warn(f"[producer] drain 超時，仍有 outstanding={out}；強制返回")
            break
        time.sleep(0.1)

    tlog(f"[producer] 已送出 {scheduled} 列，outstanding={outstanding_now(meter_fn)}")

    # ★ 事後健檢：未被 stop_event 中斷、卻未遍歷完 rows_for_count → 明確告警
    #if (total_rows is not None) and (seen < total_rows) and (not stop_event.is_set()):
    #    tlog_warn(f"⚠️ producer 迴圈提前結束：僅處理 {seen}/{total_rows} 列；已成功排程 {scheduled} 列。"
    #              " 請檢查是否有早退條件（return/break/row_limit/backpressure）、或外部執行緒誤設 stop_event。")
    # ★新增：只有「真的跑完整個 rows_for_count」且未被 stop_event 打斷才標 prod_done=True
    if (total_rows is None) or (seen >= total_rows and not stop_event.is_set()):
        try:
            meter_update(meter_fn, lambda d: d.setdefault("progress", {}).update({
                "cursor": seen, "enq": scheduled, "producer_alive": False,
                "last_progress_ts": time.time(), "prod_done": True
            }))
        except Exception:
            pass
    else:
        try:
            meter_update(meter_fn, lambda d: d.setdefault("progress", {}).update({
                "cursor": seen, "enq": scheduled, "producer_alive": False,
                "last_progress_ts": time.time(), "prod_done": False
            }))
        except Exception:
            pass

    return scheduled

def produce_rows_OLD_1029(
    ctx,
    rows_for_count: Iterable[Tuple[Any, str]],
    registry,
    meter_fn: str,
    low: int,
    stop_event,
    consumer,
    p_sched,
    gui=None,
    p_done: Optional[object] = None,   # 若傳入，遇到空字串時順手把完成條 +1
):
    """
    逐列排程並處理背壓。回傳實際排程的列數。
    - rows_for_count: [(pk, text), ...]
    - low: 背壓低水位，outstanding > low 時會暫停排程
    """
    scheduled = 0

    for idx, (pk, text) in enumerate(rows_for_count):
        if stop_event.is_set():
            tlog_warn("produce_rows: stop_event set，提前結束排程。")
            break

        # 空內容：不會產生 TODO/Success，直接把條形圖補上即可
        if not text:
            try:
                p_sched.update(1)
            except Exception:
                pass
            if gui:
                try:
                    gui.inc_sched(1)
                except Exception:
                    pass
            if p_done is not None:
                try:
                    p_done.update(1)
                except Exception:
                    pass
                if gui:
                    try:
                        gui.inc_done(1)
                    except Exception:
                        pass
            continue

        # 背壓等待
        producer_backpressure_wait(
            ctx=ctx,
            low=low,
            meter_fn=meter_fn,
            stop_event=stop_event,
            consumer_thread=consumer,
            registry=registry,
            soft_timeout=getattr(ctx, "bp_soft_timeout", 30.0),
            hard_timeout=getattr(ctx, "bp_hard_timeout", 120.0),
            sleep_step=0.05,
        )

        # 送進一列
        schedule_one_row(ctx, registry, meter_fn, idx, pk, text)
        scheduled += 1

        # 視覺更新
        try:
            p_sched.update(1)
        except Exception:
            pass
        if gui:
            try:
                gui.inc_sched(1)
            except Exception:
                pass

        # 控制 outstanding 量
        while not stop_event.is_set() and outstanding_now(meter_fn) > low:
            time.sleep(0.05)

    return scheduled
