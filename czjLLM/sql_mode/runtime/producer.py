# sql_mode/runtime/producer.py
import time
from typing import Iterable, Tuple, Any, Optional

from czjLLM.job_manager.console_ui import tlog_warn,tlog
from czjLLM.prompt_pipeline.pipeline_controller import producer_backpressure_wait
from czjLLM.prompt_pipeline.pipeline_controller import meter_update
from .workers import outstanding_now
from .scheduler import schedule_one_row


def _row_still_pending(ctx, pk) -> bool:
    """真正切片前重新確認遠端 SQL/ES 來源仍未完成，避免排程重疊造成重複計算。"""
    adapter = getattr(ctx, "_source_adapter", None)
    mode = str(getattr(ctx, "mode", "")).lower()
    if adapter is None or mode not in {"sql", "es"}:
        return True
    try:
        if mode == "es":
            cfg = getattr(adapter, "cfg", {}) or {}
            return bool(adapter.is_row_pending(
                src_table=cfg.get("src_index"),
                tgt_table=cfg.get("tgt_index") or cfg.get("src_index"),
                pk=getattr(ctx, "primary_key", cfg.get("pk_field", "_id")),
                pk_value=pk,
                input_col=getattr(ctx, "input_col", cfg.get("input_col")),
                output_col=getattr(ctx, "output_col", cfg.get("output_col", "LLM_result")),
            ))
        return bool(adapter.is_row_pending(
            src_table=getattr(ctx, "sql_table"),
            tgt_table=getattr(ctx, "target_table", getattr(ctx, "sql_table", None)),
            pk=getattr(ctx, "primary_key"),
            pk_value=pk,
            input_col=getattr(ctx, "input_col"),
            output_cols=[getattr(ctx, "output_col")],
        ))
    except AttributeError:
        return True
    except Exception as ex:
        tlog_warn(f"[producer] 重新確認列狀態失敗 pk={pk}: {ex!r}；保守繼續排程。")
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

    for idx, (pk, text) in enumerate(rows_for_count):
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

        producer_backpressure_wait(
            ctx=ctx, low=low, meter_fn=meter_fn, stop_event=stop_event,
            consumer_thread=consumer, registry=registry,
            soft_timeout=getattr(ctx, "bp_soft_timeout", 30.0),
            hard_timeout=getattr(ctx, "bp_hard_timeout", 120.0),
            sleep_step=0.05,
        )

        if not _row_still_pending(ctx, pk):
            tlog(f"[producer] pk={pk} 已由其他程序完成，略過切片與派工。")
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
                    "last_progress_ts": time.time(), "last_skipped_pk": str(pk)
                }))
            except Exception:
                pass
            continue

        try:
            schedule_one_row(ctx, registry, meter_fn, idx, pk, text)
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