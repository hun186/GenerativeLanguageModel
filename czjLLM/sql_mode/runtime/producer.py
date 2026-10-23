# sql_mode/runtime/producer.py
import random
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Iterable, Tuple, Any, Optional

from czjLLM.job_manager.console_ui import tlog_warn,tlog
from czjLLM.utilities.processing_quality import emit_quality_event
from czjLLM.prompt_pipeline.pipeline_controller import producer_backpressure_wait
from czjLLM.prompt_pipeline.pipeline_controller import meter_update
from czjLLM.prompt_pipeline.runtime_support.stage_mode import explicit_stage_flow
from czjLLM.prompt_pipeline.dispatch_parallelism import cap_orchestration_workers
from .workers import outstanding_now
from .scheduler import schedule_one_row
from .pending_recheck import (
    announce_pending_recheck_if_enabled,
    pending_recheck_stats,
    record_pending_skip,
    still_pending_before_dispatch,
    still_pending_for_running_finalize,
)
from czjLLM.prompt_pipeline.pending_central import (
    finalize_scheduled,
    is_running,
    mark_not_running,
    mark_running,
    order_rows_avoiding_running,
    record_adjustment,
)
from czjLLM.reduction.execution import ExecutionCancelled
from czjLLM.reduction.production_control import execution_cancel_requested


def _audit_producer_operational_failure(ctx, code: str) -> None:
    """Observe a caught Producer failure without changing its control flow.

    Only fixed run-scoped codes are allowed; do not pass PK, input text,
    exception messages, configuration, file paths or stage payloads.
    """
    try:
        emit_quality_event(
            getattr(ctx, "llm_call_audit_path", ""),
            run_id=getattr(ctx, "llm_call_audit_run_id", ""),
            event="producer_operational_failure", code=code,
            scope="run", outcome="observed",
        )
    except Exception as audit_error:
        # A broken quality log must never fail the Producer/retry process.
        try:
            tlog_warn(
                "[producer] quality audit failed: "
                f"{type(audit_error).__name__}"
            )
        except Exception:
            pass


def _get_positive_int(ctx, *names: str, default: int = 0) -> int:
    for name in names:
        raw = getattr(ctx, name, None)
        if raw is None:
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return default


def _get_positive_float(ctx, *names: str, default: float = 0.0) -> float:
    for name in names:
        raw = getattr(ctx, name, None)
        if raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return default


def _maybe_block_shuffle_rows(ctx, rows_for_count):
    """Keep outer block order stable while shuffling rows inside each block.

    This reduces lock-step duplication when multiple producer processes read the
    same pending sequence, without globally randomizing the workload order.
    Disabled by default; enable with one of:
      - pending_recheck_shuffle_block_size: 20
      - producer_shuffle_block_size: 20
    Optional deterministic seed:
      - pending_recheck_shuffle_seed: 1234
      - producer_shuffle_seed: 1234
    """
    block_size = _get_positive_int(
        ctx,
        "pending_recheck_shuffle_block_size",
        "producer_shuffle_block_size",
        default=0,
    )
    if block_size <= 1:
        return rows_for_count

    rows = list(rows_for_count)
    if len(rows) <= 1:
        return rows

    seed = getattr(
        ctx,
        "pending_recheck_shuffle_seed",
        getattr(ctx, "producer_shuffle_seed", None),
    )
    rng = random.Random(seed) if seed is not None else random.Random()
    shuffled = []
    for start in range(0, len(rows), block_size):
        block = rows[start:start + block_size]
        rng.shuffle(block)
        shuffled.extend(block)

    tlog(
        "[producer] pending recheck block shuffle enabled: "
        f"rows={len(rows)}, block_size={block_size}, blocks={(len(rows) + block_size - 1) // block_size}"
    )
    return shuffled


def _wait_before_revisiting_all_running_rows(ctx, rows, stop_event) -> None:
    wait_seconds = _get_positive_float(
        ctx,
        "pending_running_all_deferred_wait_seconds",
        "pending_running_wait_seconds",
        default=120.0,
    )
    if wait_seconds <= 0 or not rows:
        return

    poll_seconds = _get_positive_float(
        ctx,
        "pending_running_poll_seconds",
        default=1.0,
    )
    clear_grace_seconds = _get_positive_float(
        ctx,
        "pending_running_clear_grace_seconds",
        default=3.0,
    )
    deadline = time.time() + wait_seconds
    row_count = len(rows)
    tlog(
        "[producer] pending running console: all candidate rows are already running; "
        f"wait up to {wait_seconds:.1f}s before fallback revisit. rows={row_count}"
    )

    while not stop_event.is_set() and time.time() < deadline:
        running_count = sum(1 for row in rows if is_running(ctx, row[0]))
        if running_count <= 0:
            if clear_grace_seconds > 0:
                tlog(
                    "[producer] pending running console: running rows cleared; "
                    f"wait {clear_grace_seconds:.1f}s for DB writeback visibility before recheck."
                )
                end_grace = time.time() + clear_grace_seconds
                while not stop_event.is_set() and time.time() < end_grace:
                    time.sleep(min(0.2, max(end_grace - time.time(), 0)))
            return
        sleep_for = min(poll_seconds, max(deadline - time.time(), 0))
        if sleep_for > 0:
            time.sleep(sleep_for)

    if not stop_event.is_set():
        tlog_warn(
            "[producer] pending running console: all-running wait timed out; "
            "fallback revisit will rely on dispatch pending recheck and may duplicate work if peer is still running."
        )


def _stream_multistage_enabled(ctx) -> bool:
    mode = str(getattr(ctx, "mode", "") or "").strip().lower()
    return (
        mode in {"sql", "table", "es"}
        and bool(getattr(ctx, "sql_enable_multistage_stream", True))
        and bool(explicit_stage_flow(ctx))
    )


def _endpoint_pool_parallelism(ctx) -> int:
    """Return the same endpoint-pool-derived budget used by legacy LLM rounds."""
    try:
        n_process = int(getattr(ctx, "n_process", 0) or 0)
    except (TypeError, ValueError):
        n_process = 0
    if n_process > 0:
        return n_process

    model_spec = getattr(ctx, "model_spec", {}) or {}
    base_urls = model_spec.get("base_url") if isinstance(model_spec, dict) else None
    if isinstance(base_urls, str):
        return 1
    if isinstance(base_urls, (list, tuple, set)):
        endpoint_count = len([url for url in base_urls if url])
        if endpoint_count > 0:
            return endpoint_count * 2 if bool(getattr(ctx, "on_premises", True)) else endpoint_count
    return 1


def _multistage_row_parallelism(ctx) -> int:
    """Return bounded row/doc-level parallelism for stream multistage scheduling.

    Explicit config wins:
      - multistage_row_parallelism
      - sql_multistage_row_parallelism
      - stream_multistage_row_parallelism

    Without explicit config, reuse the endpoint-pool-derived ctx.n_process budget
    used by legacy single-stage LLM rounds. Do not infer GPU count from the
    producer host because stream jobs usually call Ollama/OpenAI-compatible APIs
    that may run on a different machine than the dispatcher.
    """
    configured = _get_positive_int(
        ctx,
        "multistage_row_parallelism",
        "sql_multistage_row_parallelism",
        "stream_multistage_row_parallelism",
        default=0,
    )
    if configured > 0:
        return configured

    return _endpoint_pool_parallelism(ctx)


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
    cancelled = execution_cancel_requested(ctx)
    rows_for_count = _maybe_block_shuffle_rows(ctx, rows_for_count)
    rows_for_count = order_rows_avoiding_running(ctx, rows_for_count)
    scheduled_pks = []
    try:
        total_rows = len(rows_for_count)  # 若是 list 可取得，generator 會丟 TypeError
    except TypeError:
        total_rows = None

    recheck_enabled = announce_pending_recheck_if_enabled(ctx)

    if total_rows is not None:
        suffix = "；pending recheck=enabled" if recheck_enabled else ""
        tlog(f"[producer] will iterate {total_rows} rows{suffix}")

    row_parallelism = _multistage_row_parallelism(ctx) if _stream_multistage_enabled(ctx) else 1
    effective_row_parallelism = cap_orchestration_workers(ctx, row_parallelism)
    executor = None
    in_flight = set()
    if effective_row_parallelism > 1:
        executor = ThreadPoolExecutor(
            max_workers=effective_row_parallelism,
            thread_name_prefix="multistage-row",
        )
        tlog(
            "[producer] multistage row/doc parallelism enabled: "
            f"max_workers={effective_row_parallelism}"
        )

    def _complete_future(fut):
        pk_done = None
        try:
            pk_done, scheduled_ok = fut.result()
            return bool(scheduled_ok), pk_done
        except ExecutionCancelled:
            raise
        except Exception as e:
            _audit_producer_operational_failure(ctx, "PRODUCER_FUTURE_EXCEPTION")
            tlog_warn(f"[producer] multistage row future failed: {e!r}")
            return False, pk_done

    def _drain_completed(block: bool = False):
        nonlocal scheduled, cancelled
        if not in_flight:
            return
        done = set()
        if block:
            done, _pending = wait(in_flight, return_when=FIRST_COMPLETED)
        else:
            done = {fut for fut in in_flight if fut.done()}
        for fut in done:
            in_flight.discard(fut)
            try:
                scheduled_ok, pk_done = _complete_future(fut)
            except ExecutionCancelled:
                cancelled = True
                continue
            if scheduled_ok:
                scheduled += 1
                if pk_done is not None:
                    scheduled_pks.append(pk_done)
            try: p_sched.update(1)
            except Exception: pass
            if gui:
                try: gui.inc_sched(1)
                except Exception: pass

    def _schedule_row(pk, text, source_inputs, row_idx_for_schedule, cursor_seen):
        if not still_pending_before_dispatch(ctx, pk):
            tlog_warn(
                f"[producer] pending recheck 命中：pk={pk} 已由其他程序完成，"
                "略過本次切片/派工以節省算力。"
            )
            if p_done is not None:
                try: p_done.update(1)
                except Exception: pass
                if gui:
                    try: gui.inc_done(1)
                    except Exception: pass
            try:
                record_pending_skip(ctx, pk)
                mark_not_running(ctx, pk, state="completed")
            except Exception as e:
                tlog_warn(f"[producer] pending skip log 寫入失敗 pk={pk}: {e!r}")
            try:
                meter_update(meter_fn, lambda d: d.setdefault("progress", {}).update({
                    "cursor": cursor_seen, "enq": scheduled, "producer_alive": True,
                    "last_progress_ts": time.time(),
                    "last_skip_reason": "already_completed", "last_skip_pk": pk
                }))
            except Exception:
                pass
            return pk, False

        try:
            mark_running(ctx, pk)
            record_adjustment(ctx, "mark_running_before_dispatch", pk=pk)
            try:
                scheduled_chunks = schedule_one_row(
                    ctx, registry, meter_fn, row_idx_for_schedule, pk, text,
                    source_inputs=source_inputs,
                )
            except ExecutionCancelled:
                raise
            except Exception:
                # Bookkeeping (mark_running/record_adjustment/no-op release)
                # also lives in the enclosing try, but is not a scheduler
                # execution failure. Emit only for schedule_one_row itself.
                _audit_producer_operational_failure(
                    ctx, "PRODUCER_SCHEDULE_EXCEPTION"
                )
                raise
            try:
                scheduled_chunk_count = int(scheduled_chunks or 0)
            except (TypeError, ValueError):
                scheduled_chunk_count = 0
            if scheduled_chunk_count <= 0:
                mark_not_running(ctx, pk, state="schedule_noop")
                record_adjustment(ctx, "schedule_noop_release", pk=pk)
                tlog_warn(
                    f"[producer] schedule_one_row 未建立可執行任務 pk={pk}；"
                    "已釋放 pending running console 標記，避免其他程序持續延後。"
                )
                return pk, False
            return pk, True
        except ExecutionCancelled:
            # Preserve the cooperative cancellation even if pending-console
            # cleanup also fails. Otherwise a cleanup exception replaces
            # ExecutionCancelled in fut.result(), and _drain_completed()
            # falsely records a producer future failure instead of cancelling.
            for cleanup in (
                lambda: mark_not_running(ctx, pk, state="cancelled"),
                lambda: record_adjustment(ctx, "cancelled_release", pk=pk),
            ):
                try:
                    cleanup()
                except Exception as cleanup_error:
                    try:
                        tlog_warn(
                            "[producer] cancellation cleanup failed: "
                            f"{type(cleanup_error).__name__}"
                        )
                    except Exception:
                        pass
            raise
        except Exception as e:
            try:
                mark_not_running(ctx, pk, state="schedule_error")
                record_adjustment(ctx, "schedule_error_release", pk=pk,
                                  error_type=type(e).__name__)
            except Exception:
                pass
            tlog_warn(f"[producer] schedule_one_row 失敗 pk={pk}: {e!r}")
            return pk, False

    fallback_running_phase = False
    deferred_running_rows = []
    idx = 0
    try:
        while idx < len(rows_for_count):
            _drain_completed(block=False)
            while (
                executor is not None
                and len(in_flight) >= effective_row_parallelism
                and not stop_event.is_set() and not execution_cancel_requested(ctx)
            ):
                _drain_completed(block=True)
            if execution_cancel_requested(ctx) or cancelled:
                cancelled = True
                break
            row = rows_for_count[idx]
            idx += 1
            if len(row) >= 3:
                pk, text, source_inputs = row[0], row[1], row[2]
            else:
                pk, text = row[0], row[1]
                source_inputs = None
            seen += 1

            if (not fallback_running_phase) and is_running(ctx, pk):
                record_adjustment(ctx, "defer_running", pk=pk, deferred_count=len(deferred_running_rows) + 1)
                deferred_running_rows.append(row)
                if idx >= len(rows_for_count) and deferred_running_rows:
                    _wait_before_revisiting_all_running_rows(ctx, deferred_running_rows, stop_event)
                    rows_for_count = deferred_running_rows
                    deferred_running_rows = []
                    idx = 0
                    fallback_running_phase = True
                    record_adjustment(ctx, "fallback_revisit_running", deferred=len(rows_for_count))
                    tlog(
                        "[producer] pending running console: all non-running rows scanned; "
                        f"revisit deferred running rows={len(rows_for_count)}"
                    )
                continue

            if stop_event.is_set() or execution_cancel_requested(ctx):
                cancelled = cancelled or execution_cancel_requested(ctx)
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
                if not isinstance(e, ExecutionCancelled):
                    _audit_producer_operational_failure(
                        ctx, "PRODUCER_BACKPRESSURE_EXCEPTION"
                    )
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

            if execution_cancel_requested(ctx):
                cancelled = True
                break
            if executor is not None:
                in_flight.add(executor.submit(_schedule_row, pk, text, source_inputs, idx - 1, seen))
            else:
                pk_done, scheduled_ok = _schedule_row(pk, text, source_inputs, idx - 1, seen)
                if scheduled_ok:
                    scheduled_pks.append(pk_done)
                    scheduled += 1
                try: p_sched.update(1)
                except Exception: pass
                if gui:
                    try: gui.inc_sched(1)
                    except Exception: pass

            # ★新增：每送一列即回報游標/送件數
            try:
                meter_update(meter_fn, lambda d: d.setdefault("progress", {}).update({
                    "cursor": seen, "enq": scheduled + len(in_flight), "producer_alive": True,
                    "last_progress_ts": time.time()
                }))
            except Exception:
                pass

            while (not stop_event.is_set() and not execution_cancel_requested(ctx)
                   and outstanding_now(meter_fn) > low):
                _drain_completed(block=False)
                time.sleep(0.05)
    except ExecutionCancelled:
        cancelled = True
    finally:
        while in_flight:
            _drain_completed(block=True)
        if executor is not None:
            executor.shutdown(wait=True)

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

    if recheck_enabled:
        stats = pending_recheck_stats(ctx)
        tlog(
            "[producer] pending recheck dispatch summary: "
            f"checked={stats['checked']}, pending={stats['pending']}, "
            f"already_completed={stats['already_completed']}, errors={stats['errors']}"
        )

    finalize_scheduled(ctx, scheduled_pks, pending_check=still_pending_for_running_finalize)
    try:
        ctx._pending_recheck_scheduled_pks = tuple(scheduled_pks)
    except Exception:
        pass

    if recheck_enabled:
        finalize_stats = pending_recheck_stats(ctx, scope="finalize")
        tlog(
            "[producer] pending running finalize recheck summary: "
            f"checked={finalize_stats['checked']}, pending={finalize_stats['pending']}, "
            f"already_completed={finalize_stats['already_completed']}, errors={finalize_stats['errors']}"
        )

    if recheck_enabled:
        stats = pending_recheck_stats(ctx)
        tlog(
            "[producer] pending recheck summary: "
            f"checked={stats['checked']}, pending={stats['pending']}, "
            f"already_completed={stats['already_completed']}, errors={stats['errors']}"
        )

    tlog(f"[producer] 已送出 {scheduled} 列，outstanding={outstanding_now(meter_fn)}")
    try:
        ctx._producer_cancelled = bool(cancelled)
        ctx._producer_seen_rows = seen
    except Exception:
        pass

    # ★ 事後健檢：未被 stop_event 中斷、卻未遍歷完 rows_for_count → 明確告警
    #if (total_rows is not None) and (seen < total_rows) and (not stop_event.is_set()):
    #    tlog_warn(f"⚠️ producer 迴圈提前結束：僅處理 {seen}/{total_rows} 列；已成功排程 {scheduled} 列。"
    #              " 請檢查是否有早退條件（return/break/row_limit/backpressure）、或外部執行緒誤設 stop_event。")
    # ★新增：只有「真的跑完整個 rows_for_count」且未被 stop_event 打斷才標 prod_done=True
    if not cancelled and ((total_rows is None) or (seen >= total_rows and not stop_event.is_set())):
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
                , "cancelled": cancelled
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
