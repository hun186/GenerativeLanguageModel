import multiprocessing
import os
import time as _time

try:
    from czjLLM.job_manager.console_ui import tlog_warn
except Exception:
    def tlog_warn(msg):
        print(msg)


CONSUMER_STATE = {
    "last_dispatch_ts": 0.0,
    "pool_alive": False,
}


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


def _run_prompt_job(job):
    """Top-level multiprocessing target so PromptAPIPipeline jobs remain picklable."""
    return job.proc()


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


def run_round(jobs, n_proc: int, timeout_sec: float | None = None):
    """Run one consumer batch with a hard wall-clock timeout."""
    use_mp = (n_proc > 1) and (len(jobs) > 1)
    timeout_sec = _round_timeout_from_jobs(jobs, timeout_sec)
    CONSUMER_STATE["pool_alive"] = False
    CONSUMER_STATE["last_round_timed_out"] = False

    if not use_mp:
        out = []
        deadline = _time.monotonic() + timeout_sec
        for j in jobs:
            if _time.monotonic() > deadline:
                CONSUMER_STATE["last_round_timed_out"] = True
                raise BatchRunTimeout(timeout_sec, len(out), len(jobs))
            try:
                out.append(j.proc())
                CONSUMER_STATE["last_dispatch_ts"] = _time.monotonic()
            except Exception as ex:
                tlog_warn(f"[single] worker error: {ex}")
        return out

    pool = None
    results = []
    try:
        CONSUMER_STATE["pool_alive"] = True
        pool = multiprocessing.Pool(processes=min(int(n_proc), len(jobs)))
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
        return results
    except multiprocessing.TimeoutError:
        CONSUMER_STATE["last_round_timed_out"] = True
        finished = len(results)
        if pool is not None:
            pool.terminate()
            pool.join()
        raise BatchRunTimeout(timeout_sec, finished, len(jobs))
    except Exception:
        if pool is not None:
            pool.terminate()
            pool.join()
        raise
    finally:
        CONSUMER_STATE["pool_alive"] = False
