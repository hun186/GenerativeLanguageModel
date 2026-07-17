import concurrent.futures
import multiprocessing
import os
import platform
import sys
import threading
import time as _time

from czjLLM.prompt_pipeline.pending_central import tlog_warn


CONSUMER_STATE = {
    "last_dispatch_ts": 0.0,
    "pool_alive": False,
}


WINDOWS_SPAWN_OVERLAP_JOIN_TIMEOUT_SEC = 0.75


class BatchRunTimeout(RuntimeError):
    """Raised when a consumer batch exceeds its wall-clock timeout."""

    def __init__(self, timeout_sec: float, finished: int, total: int):
        super().__init__(
            f"LLM batch timed out after {timeout_sec:.0f}s "
            f"(finished={finished}/{total})"
        )
        self.timeout_sec = float(timeout_sec)
        self.finished = int(finished)
        self.total = int(total)


def _normalize_job_result(job, raw):
    prompt_file = getattr(job, "promptFile", "")

    if isinstance(raw, dict):
        ok = bool(raw.get("ok"))
        error = str(raw.get("error", ""))
        output = raw.get("output")
    else:
        ok = bool(raw)
        error = ""
        output = None

    return {
        "prompt_file": prompt_file,
        "ok": ok,
        "error": error,
        "output": output,
        "raw": raw,
    }


def _run_prompt_job(job):
    """Top-level multiprocessing target so PromptAPIPipeline jobs remain picklable."""
    raw = job.proc()
    return _normalize_job_result(job, raw)


def _round_timeout_from_jobs(jobs, explicit_timeout=None) -> float:
    if explicit_timeout is not None:
        try:
            return max(1.0, float(explicit_timeout))
        except Exception:
            pass

    try:
        env_timeout = os.getenv("CZJLLM_LLM_ROUND_TIMEOUT_SEC")
        if env_timeout:
            return max(1.0, float(env_timeout))
    except Exception:
        pass

    return 480.0


def _truthy_debug_flag(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "debug"}
    return bool(value)


def _llm_round_debug_enabled(explicit=None) -> bool:
    if explicit is not None:
        return _truthy_debug_flag(explicit)
    return _truthy_debug_flag(os.getenv("CZJLLM_LLM_ROUND_DEBUG"))


def _safe_start_method() -> str:
    try:
        return multiprocessing.get_start_method(allow_none=True) or "default"
    except Exception as exc:
        return f"unavailable:{exc!r}"


def _active_children():
    try:
        return list(multiprocessing.active_children())
    except Exception:
        return None


def _active_children_count():
    children = _active_children()
    if children is None:
        return None
    return len(children)


def _safe_active_children_count() -> str:
    count = _active_children_count()
    if count is not None:
        return str(count)
    return "unavailable"


def _job_debug_summary(jobs, limit: int = 5) -> str:
    parts = []
    for job in list(jobs)[:limit]:
        cls = job.__class__
        prompt_file = getattr(job, "promptFile", "")
        parts.append(f"{cls.__module__}.{cls.__qualname__}(promptFile={prompt_file!r})")
    if len(jobs) > limit:
        parts.append(f"...(+{len(jobs) - limit} more)")
    return "; ".join(parts)


def _debug_round_message(jobs, n_proc: int, timeout_sec: float, phase: str, error=None) -> str:
    lines = [
        f"[round-debug] phase={phase}",
        f"  platform={platform.platform()}",
        f"  pid={os.getpid()}",
        f"  thread={threading.current_thread().name}",
        f"  multiprocessing_start_method={_safe_start_method()}",
        f"  active_children={_safe_active_children_count()}",
        f"  n_proc={n_proc}",
        f"  jobs={len(jobs)}",
        f"  pool_processes={min(int(n_proc), len(jobs)) if jobs else 0}",
        f"  timeout_sec={timeout_sec}",
        f"  worker_target={_run_prompt_job.__module__}.{_run_prompt_job.__qualname__}",
        f"  job_samples={_job_debug_summary(jobs)}",
    ]
    if error is not None:
        lines.append(f"  error_type={type(error).__module__}.{type(error).__qualname__}")
        lines.append(f"  error_repr={error!r}")
    return "\n".join(lines)


def _debug_round(jobs, n_proc: int, timeout_sec: float, phase: str, error=None, debug_enabled=None) -> None:
    if _llm_round_debug_enabled(debug_enabled):
        tlog_warn(_debug_round_message(jobs, n_proc, timeout_sec, phase, error=error))



def _join_existing_children_once(timeout_sec: float) -> int | None:
    children = _active_children()
    if children is None:
        return None
    for child in children:
        try:
            child.join(timeout=timeout_sec)
        except Exception as exc:
            tlog_warn(f"⚠️ Windows spawn overlap preflight: child join failed: {exc!r}")
    return _active_children_count()

'''
def _should_use_thread_pool_to_avoid_windows_spawn_overlap() -> bool:
    if not sys.platform.startswith("win"):
        return False
    count = _active_children_count()
    if not count:
        return False

    tlog_warn(
        "⚠️ Windows legacy LLM round found existing multiprocessing children "
        f"before creating a new Pool (active_children={count}); attempting a short built-in join/reap first."
    )
    remaining = _join_existing_children_once(WINDOWS_SPAWN_OVERLAP_JOIN_TIMEOUT_SEC)
    return bool(remaining and remaining > 0)
'''

def _should_use_thread_pool_to_avoid_windows_spawn_overlap() -> bool:
    if not sys.platform.startswith("win"):
        return False

    count = _active_children_count()
    if not count:
        return False

    tlog_warn(
        "⚠️ Windows legacy LLM round found existing multiprocessing children "
        f"before creating a new Pool (active_children={count}); "
        "attempting a short built-in join/reap first."
    )

    remaining = _join_existing_children_once(
        WINDOWS_SPAWN_OVERLAP_JOIN_TIMEOUT_SEC
    )

    tlog_warn(
        "⚠️ Windows 本輪曾偵測到 multiprocessing child；"
        f"join/reap 後 remaining={remaining}。"
        "為避免 Windows handle cleanup race，本輪固定改用 ThreadPool。"
    )

    # 重點：只要本輪曾看到 active child，就不要立刻再 spawn 新 Pool。
    return True
    


def _run_round_threads(jobs, n_proc: int, timeout_sec: float):
    results = []
    max_workers = max(1, min(int(n_proc), len(jobs)))
    deadline = _time.monotonic() + timeout_sec
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_run_prompt_job, job) for job in jobs]
        for fut in futures:
            remain = deadline - _time.monotonic()
            if remain <= 0:
                CONSUMER_STATE["last_round_timed_out"] = True
                for pending in futures[len(results):]:
                    pending.cancel()
                raise BatchRunTimeout(timeout_sec, len(results), len(jobs))
            try:
                results.append(fut.result(timeout=remain))
                CONSUMER_STATE["last_dispatch_ts"] = _time.monotonic()
            except concurrent.futures.TimeoutError as exc:
                CONSUMER_STATE["last_round_timed_out"] = True
                for pending in futures[len(results):]:
                    pending.cancel()
                raise BatchRunTimeout(timeout_sec, len(results), len(jobs)) from exc
    return results

def _run_round_serial(jobs, timeout_sec: float):
    out = []
    deadline = _time.monotonic() + timeout_sec
    for j in jobs:
        if _time.monotonic() > deadline:
            CONSUMER_STATE["last_round_timed_out"] = True
            raise BatchRunTimeout(timeout_sec, len(out), len(jobs))
        try:
            raw = j.proc()
            out.append(_normalize_job_result(j, raw))
            CONSUMER_STATE["last_dispatch_ts"] = _time.monotonic()
        except Exception as ex:
            tlog_warn(f"[single] worker error: {ex}")
            out.append({
                "prompt_file": getattr(j, "promptFile", ""),
                "ok": False,
                "error": str(ex),
                "output": None,
                "raw": None,
            })
    return out


'''
def run_round(jobs, n_proc: int, timeout_sec: float | None = None, debug_enabled=None):
    """Run one consumer batch with a hard wall-clock timeout."""
    use_mp = (n_proc > 1) and (len(jobs) > 1)
    timeout_sec = _round_timeout_from_jobs(jobs, timeout_sec)
    CONSUMER_STATE["pool_alive"] = False
    CONSUMER_STATE["last_round_timed_out"] = False

    if not use_mp:
        return _run_round_serial(jobs, timeout_sec)

    if _should_use_thread_pool_to_avoid_windows_spawn_overlap():
        tlog_warn(
            "⚠️ Windows legacy LLM round still has active multiprocessing children "
            "after the built-in pre-Pool join/reap; running this round with a thread pool to avoid spawn "
            "EOFError/WinError 5 during DuplicateHandle while preserving LLM I/O concurrency. "
            "This is an automatic safety path; no operator setting is required."
        )
        _debug_round(jobs, n_proc, timeout_sec, "windows_spawn_overlap_thread_fallback", debug_enabled=debug_enabled)
        return _run_round_threads(jobs, n_proc, timeout_sec)

    pool = None
    results = []
    try:
        _debug_round(jobs, n_proc, timeout_sec, "before_pool", debug_enabled=debug_enabled)
        CONSUMER_STATE["pool_alive"] = True
        pool = multiprocessing.Pool(processes=min(int(n_proc), len(jobs)))
        _debug_round(jobs, n_proc, timeout_sec, "after_pool_created", debug_enabled=debug_enabled)
        async_results = [pool.apply_async(_run_prompt_job, (job,)) for job in jobs]
        pool.close()

        deadline = _time.monotonic() + timeout_sec
        for ar in async_results:
            remain = deadline - _time.monotonic()
            if remain <= 0:
                raise multiprocessing.TimeoutError()
            results.append(ar.get(timeout=remain))
            CONSUMER_STATE["last_dispatch_ts"] = _time.monotonic()

        pool.join()
        _debug_round(jobs, n_proc, timeout_sec, "after_pool_join", debug_enabled=debug_enabled)
        return results
    except multiprocessing.TimeoutError:
        CONSUMER_STATE["last_round_timed_out"] = True
        finished = len(results)
        if pool is not None:
            pool.terminate()
            pool.join()
        ex = BatchRunTimeout(timeout_sec, finished, len(jobs))
        _debug_round(jobs, n_proc, timeout_sec, "timeout", error=ex, debug_enabled=debug_enabled)
        raise ex
    except Exception as ex:
        if pool is not None:
            pool.terminate()
            pool.join()
        _debug_round(jobs, n_proc, timeout_sec, "exception", error=ex, debug_enabled=debug_enabled)
        raise
    finally:
        CONSUMER_STATE["pool_alive"] = False
'''
def run_round(
    jobs,
    n_proc: int,
    timeout_sec: float | None = None,
    debug_enabled=None,
):
    """Run one consumer batch with a hard wall-clock timeout."""

    use_parallel = (n_proc > 1) and (len(jobs) > 1)
    timeout_sec = _round_timeout_from_jobs(jobs, timeout_sec)

    CONSUMER_STATE["pool_alive"] = False
    CONSUMER_STATE["last_round_timed_out"] = False

    # 單一工作不需要建立 executor
    if not use_parallel:
        return _run_round_serial(jobs, timeout_sec)

    # Windows 的工作主要是遠端 LLM HTTP I/O，
    # 固定使用 ThreadPool，完全避免 multiprocessing spawn、
    # DuplicateHandle、active_children 與 child.join 問題。
    if sys.platform.startswith("win"):
        tlog_warn(
            "ℹ️ Windows legacy LLM round uses ThreadPoolExecutor "
            f"(jobs={len(jobs)}, workers={min(int(n_proc), len(jobs))})"
        )

        _debug_round(
            jobs,
            n_proc,
            timeout_sec,
            "windows_thread_pool",
            debug_enabled=debug_enabled,
        )

        return _run_round_threads(jobs, n_proc, timeout_sec)

    # Linux / POSIX 保留 multiprocessing Pool
    pool = None
    results = []

    try:
        _debug_round(
            jobs,
            n_proc,
            timeout_sec,
            "before_pool",
            debug_enabled=debug_enabled,
        )

        CONSUMER_STATE["pool_alive"] = True

        pool = multiprocessing.Pool(
            processes=min(int(n_proc), len(jobs))
        )

        _debug_round(
            jobs,
            n_proc,
            timeout_sec,
            "after_pool_created",
            debug_enabled=debug_enabled,
        )

        async_results = [
            pool.apply_async(_run_prompt_job, (job,))
            for job in jobs
        ]

        pool.close()

        deadline = _time.monotonic() + timeout_sec

        for ar in async_results:
            remain = deadline - _time.monotonic()

            if remain <= 0:
                raise multiprocessing.TimeoutError()

            results.append(ar.get(timeout=remain))
            CONSUMER_STATE["last_dispatch_ts"] = _time.monotonic()

        pool.join()

        _debug_round(
            jobs,
            n_proc,
            timeout_sec,
            "after_pool_join",
            debug_enabled=debug_enabled,
        )

        return results

    except multiprocessing.TimeoutError:
        CONSUMER_STATE["last_round_timed_out"] = True
        finished = len(results)

        if pool is not None:
            pool.terminate()
            pool.join()

        ex = BatchRunTimeout(
            timeout_sec,
            finished,
            len(jobs),
        )

        _debug_round(
            jobs,
            n_proc,
            timeout_sec,
            "timeout",
            error=ex,
            debug_enabled=debug_enabled,
        )

        raise ex

    except Exception as ex:
        if pool is not None:
            pool.terminate()
            pool.join()

        _debug_round(
            jobs,
            n_proc,
            timeout_sec,
            "exception",
            error=ex,
            debug_enabled=debug_enabled,
        )

        raise

    finally:
        CONSUMER_STATE["pool_alive"] = False