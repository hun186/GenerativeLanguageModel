"""Offline-proven slot refill primitive; NOT wired to live Consumer.

The caller retains authority over filesystem Queue Claim, Worker execution,
Success no-clobber, resource limits and meter acknowledgements. No job is
replayed, unclaimed, or implicitly marked as persisted by this module.
"""
from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass
import time
from typing import Any, Callable


@dataclass(frozen=True)
class ClaimedWork:
    receipt: str
    item: Any


@dataclass(frozen=True)
class RefillStats:
    claimed: int
    acknowledged: int
    max_inflight_observed: int


class RefillAborted(RuntimeError):
    def __init__(self, reason: str, stats: RefillStats):
        super().__init__(reason)
        self.reason = reason
        self.stats = stats


def run_slot_refill(
    *, claim_one: Callable[[], ClaimedWork | None],
    run_worker: Callable[[Any], Any],
    acknowledge: Callable[[ClaimedWork, Any], None],
    max_inflight: int,
    deadline_sec: float | None = None,
    stop_requested: Callable[[], bool] | None = None,
    producer_done: Callable[[], bool] | None = None,
    empty_poll_seconds: float = 0.05,
) -> RefillStats:
    """Refill a slot only after the completed Worker is acknowledged.

    The claim callback MUST perform the real exclusive Queue Claim and return
    its actual receipt. The acknowledgement callback MUST confirm persistence
    (or explicitly mark a failed/incomplete item). If either fails, abort
    dispatch and drain all in-flight Workers; do not auto-replay any claims.
    """
    if type(max_inflight) is not int or not 1 <= max_inflight <= 256:
        raise ValueError("invalid refill worker limit")
    if deadline_sec is not None and (
        type(deadline_sec) not in (int, float) or deadline_sec <= 0
    ):
        raise ValueError("invalid refill deadline")
    if not 0.01 <= empty_poll_seconds <= 5:
        raise ValueError("invalid empty poll interval")
    until = time.monotonic() + deadline_sec if deadline_sec else None
    claimed, acknowledged, peak = 0, 0, 0
    seen = set()
    active = {}

    def snapshot():
        return RefillStats(claimed=claimed, acknowledged=acknowledged,
                           max_inflight_observed=peak)

    def check_active():
        if stop_requested is not None and stop_requested():
            raise RefillAborted("stop_requested", snapshot())
        if until is not None and time.monotonic() >= until:
            raise RefillAborted("deadline_exceeded", snapshot())

    # ThreadPoolExecutor shutdown(wait=True) makes running tasks drain before
    # a raised failure can escape to a coordinator that might retry work.
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_inflight) as executor:
        try:
            while True:
                check_active()
                no_claim = False
                while len(active) < max_inflight:
                    check_active()
                    next_work = claim_one()
                    if next_work is None:
                        no_claim = True
                        break
                    if (not isinstance(next_work, ClaimedWork)
                            or not isinstance(next_work.receipt, str)
                            or not next_work.receipt):
                        raise ValueError("claim requires nonempty receipt")
                    if next_work.receipt in seen:
                        raise ValueError("replayed claim receipt")
                    seen.add(next_work.receipt)
                    claimed += 1
                    future = executor.submit(run_worker, next_work.item)
                    active[future] = next_work
                    peak = max(peak, len(active))
                if not active:
                    if producer_done is None or producer_done():
                        return snapshot()
                    check_active()
                    time.sleep(empty_poll_seconds)
                    continue

                timeout = (empty_poll_seconds if until is None
                           else max(0.0, min(empty_poll_seconds, until - time.monotonic())))
                done, _ = concurrent.futures.wait(
                    active, timeout=timeout,
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )
                if not done:
                    check_active()
                    continue
                # Always acknowledge before claiming a replacement. Future
                # completion != Queue Success or SQL/ES sink ACK.
                for future in done:
                    claim = active.pop(future)
                    result = future.result()
                    acknowledge(claim, result)
                    acknowledged += 1
        except BaseException:
            # No orphaned queued work is silently detached or restarted.
            for future in active:
                future.cancel()
            raise
