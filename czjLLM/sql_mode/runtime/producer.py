# sql_mode/runtime/producer.py
import time
from typing import Iterable, Tuple, Any, Optional

from czjLLM.job_manager.console_ui import tlog_warn
from czjLLM.prompt_pipeline.pipeline_controller import producer_backpressure_wait
from .workers import outstanding_now
from .scheduler import schedule_one_row

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