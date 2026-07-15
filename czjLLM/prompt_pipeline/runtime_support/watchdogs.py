"""Watchdog helpers for prompt pipeline progress and Elasticsearch heartbeat checks."""

import faulthandler
import os
import threading
import time
from datetime import datetime

from czjLLM.prompt_pipeline.runtime_support.load_meter import meter_read
from czjLLM.prompt_pipeline.round_runner import CONSUMER_STATE


def _es_heartbeat_loop(adapter, interval_sec=60):
    while True:
        try:
            ok = bool(getattr(adapter, "es", None)) and adapter.es.ping(request_timeout=3)
            if not ok:
                print("[watchdog] ES ping 失敗", flush=True)
        except Exception as e:
            print(f"[watchdog] ES ping 例外: {e}", flush=True)
        time.sleep(interval_sec)


def _stall_watchdog(ctx, adapter, idle_threshold_sec=600, interval_sec=60,
                    stacks_path="stacks.log", meter_fn=None, restart_cb=None):
    stacks_file = open(stacks_path, "a", buffering=1, encoding="utf-8")
    no_chunk_threshold_sec = float(getattr(ctx, "no_chunk_complete_timeout_sec", 5 * 60 * 60) or 0)
    fatal_on_no_chunk = bool(getattr(ctx, "fatal_on_no_chunk_stall", True))
    last_completed = None
    last_completed_change_ts = time.time()
    no_chunk_stall_reported = False
    try:
        faulthandler.enable()
    except Exception:
        pass

    max_stacks_bytes = 20 * 1024 * 1024

    while True:
        try:
            now = time.time()

            m = {}
            q = {}
            consumer = {}
            try:
                m = meter_read(meter_fn) if meter_fn else {}
                q = m.get("queue", {}) if isinstance(m, dict) else {}
                consumer = m.get("consumer", {}) if isinstance(m, dict) else {}
            except Exception:
                m, q, consumer = {}, {}, {}

            pending = int(q.get("pending", 0) or 0)
            running = int(q.get("running", 0) or 0)
            completed = int(q.get("completed", 0) or 0)

            if last_completed is None or completed != last_completed:
                last_completed = completed
                last_completed_change_ts = now
                no_chunk_stall_reported = False
            elif (
                no_chunk_threshold_sec > 0
                and (pending + running) > 0
                and (now - last_completed_change_ts) >= no_chunk_threshold_sec
                and not no_chunk_stall_reported
            ):
                msg = (
                    f"[watchdog][FATAL] {int(now - last_completed_change_ts)} 秒沒有任何分片完成 "
                    f"(threshold={int(no_chunk_threshold_sec)}s, pending={pending}, "
                    f"running={running}, completed={completed}, pid={os.getpid()}, meter={meter_fn})；"
                    "終止主程序以避免排程堆積耗盡記憶體。"
                )
                print(msg, flush=True)
                try:
                    stacks_file.write(f"\n{datetime.now().isoformat()} {msg}\n")
                    faulthandler.dump_traceback(file=stacks_file)
                except Exception as e:
                    print(f"[watchdog] fatal stall log/dump 例外: {e}", flush=True)
                no_chunk_stall_reported = True
                if fatal_on_no_chunk:
                    try:
                        stacks_file.flush()
                    except Exception:
                        pass
                    os._exit(2)

            last_doc = getattr(ctx, "last_progress_ts", None)
            last_round = consumer.get("last_round_ts", None)
            last_dispatch_mono = CONSUMER_STATE.get("last_dispatch_ts", 0.0)

            if last_dispatch_mono:
                last_dispatch = now - max(0.0, (time.monotonic() - last_dispatch_mono))
            else:
                last_dispatch = None

            candidates = [t for t in [last_doc, last_round, last_dispatch] if isinstance(t, (int, float)) and t > 0]
            last_any = max(candidates) if candidates else None
            idle = now - last_any if last_any is not None else 0

            alive_hint = False
            if running > 0:
                if (last_round and now - float(last_round) < 120) or (last_dispatch and now - float(last_dispatch) < 120):
                    alive_hint = True

            if (idle > idle_threshold_sec) and (not alive_hint):
                print("[watchdog] 10 分鐘無進度訊號（doc/round/dispatch），疑似停滯，請檢查 stacks.log 與 ES", flush=True)

                try:
                    if os.path.exists(stacks_path) and os.path.getsize(stacks_path) > max_stacks_bytes:
                        try:
                            stacks_file.close()
                        except Exception:
                            pass
                        stacks_file = open(stacks_path, "w", buffering=1, encoding="utf-8")
                        print(f"[watchdog] stacks.log 超過上限，已截斷重建（上限 {max_stacks_bytes} bytes）", flush=True)
                except Exception as e:
                    print(f"[watchdog] 檔案大小檢查失敗：{e}", flush=True)

                try:
                    faulthandler.dump_traceback(file=stacks_file)
                except Exception as e:
                    print(f"[watchdog] dump 例外: {e}", flush=True)

                try:
                    ok = bool(getattr(adapter, "es", None)) and adapter.es.ping(request_timeout=3)
                    if not ok:
                        print("[watchdog] ES ping 失敗（stall）", flush=True)
                except Exception as e:
                    print(f"[watchdog] ES ping 例外（stall）: {e}", flush=True)

            try:
                long_no_dispatch = (time.monotonic() - CONSUMER_STATE.get("last_dispatch_ts", 0.0) > 120.0)
                if pending > 0 and running == 0 and long_no_dispatch:
                    print("🧯 [watchdog] stall detected: pending>0, running=0, long_no_dispatch>120s", flush=True)
                    if callable(restart_cb):
                        try:
                            restart_cb()
                            print("🔄 [watchdog] restart_cb invoked", flush=True)
                        except Exception as re:
                            print(f"⚠️ [watchdog] restart_cb error: {re}", flush=True)
            except Exception:
                pass

        except Exception as e:
            print(f"[watchdog] 自身例外: {e}", flush=True)

        time.sleep(interval_sec)


def _stall_watchdog_0119(ctx, adapter, idle_threshold_sec=600, interval_sec=60, stacks_path="stacks.log", meter_fn=None, restart_cb=None):
    stacks_file = open(stacks_path, "a", buffering=1, encoding="utf-8")
    try:
        faulthandler.enable()
    except Exception:
        pass

    max_stacks_bytes = 20 * 1024 * 1024

    while True:
        try:
            last = getattr(ctx, "last_progress_ts", None)
            if last is not None:
                idle = time.time() - last
                if idle > idle_threshold_sec:
                    print("[watchdog] 進度 10 分鐘無前進，疑似停滯，請檢查 stacks.log 與 ES", flush=True)

                    try:
                        if os.path.exists(stacks_path) and os.path.getsize(stacks_path) > max_stacks_bytes:
                            try:
                                stacks_file.close()
                            except Exception:
                                pass
                            stacks_file = open(stacks_path, "w", buffering=1, encoding="utf-8")
                            print(f"[watchdog] stacks.log 超過上限，已截斷重建（上限 {max_stacks_bytes} bytes）", flush=True)
                    except Exception as e:
                        print(f"[watchdog] 檔案大小檢查失敗：{e}", flush=True)

                    try:
                        faulthandler.dump_traceback(file=stacks_file)
                    except Exception as e:
                        print(f"[watchdog] dump 例外: {e}", flush=True)
                    try:
                        ok = bool(getattr(adapter, "es", None)) and adapter.es.ping(request_timeout=3)
                        if not ok:
                            print("[watchdog] ES ping 失敗（stall）", flush=True)
                    except Exception as e:
                        print(f"[watchdog] ES ping 例外（stall）: {e}", flush=True)
            try:
                m = meter_read(meter_fn) if meter_fn else {}
                q = m.get("queue", {})
                pending = int(q.get("pending", 0) or 0)
                running = int(q.get("running", 0) or 0)
                long_no_dispatch = (time.monotonic() - CONSUMER_STATE.get("last_dispatch_ts", 0.0) > 120.0)
                if pending > 0 and running == 0 and long_no_dispatch:
                    print("🧯 [watchdog] stall detected: pending>0, running=0, long_no_dispatch>120s", flush=True)
                    if callable(restart_cb):
                        try:
                            restart_cb()
                            print("🔄 [watchdog] restart_cb invoked", flush=True)
                        except Exception as re:
                            print(f"⚠️ [watchdog] restart_cb error: {re}", flush=True)
            except Exception:
                pass
        except Exception as e:
            print(f"[watchdog] 自身例外: {e}", flush=True)
        time.sleep(interval_sec)


def start_watchdogs(ctx, adapter=None, *,
                    ping_interval_sec=60,
                    stall_idle_threshold_sec=600,
                    stall_interval_sec=60,
                    stacks_path=None,
                    meter_fn=None,
                    restart_cb=None):
    """
    從 controller 啟動所有 watchdog。
    - ctx: 需要 last_progress_ts（orchestrator 每前進一次要更新）
    - adapter: ES 時傳入 ElasticsearchAdapter；其他 backend 可傳 None
    """
    if getattr(ctx, "_watchdogs_started", False):
        return
    setattr(ctx, "_watchdogs_started", True)

    if getattr(ctx, "last_progress_ts", None) is None:
        ctx.last_progress_ts = time.time()

    if stacks_path is None:
        stacks_path = os.path.join(getattr(ctx, "work_dir", "."), "stacks.log")

    threading.Thread(
        target=_stall_watchdog,
        args=(ctx, adapter),
        kwargs=dict(
            idle_threshold_sec=stall_idle_threshold_sec,
            interval_sec=stall_interval_sec,
            stacks_path=stacks_path,
            meter_fn=meter_fn,
            restart_cb=restart_cb,
        ),
        daemon=True,
    ).start()

    if adapter is not None and getattr(adapter, "es", None) is not None:
        threading.Thread(
            target=_es_heartbeat_loop,
            args=(adapter,),
            kwargs=dict(interval_sec=ping_interval_sec),
            daemon=True,
        ).start()
