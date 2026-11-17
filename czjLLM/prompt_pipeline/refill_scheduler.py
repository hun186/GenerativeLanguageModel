"""Slot-refill primitive used by the Windows legacy Consumer.

The caller retains authority over filesystem Queue Claim, Worker execution,
Success no-clobber, resource limits and Meter queue-transition ACKs. This
scheduler never implies that a SQL/ES sink writeback was confirmed, nor does
it replay or unclaim failed work. Linux and stage-managed paths stay separate.
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
    drain_on_deadline: bool = False,
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
    if type(drain_on_deadline) is not bool:
        raise ValueError("invalid deadline drain flag")
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
        if (not drain_on_deadline and until is not None
                and time.monotonic() >= until):
            raise RefillAborted("deadline_exceeded", snapshot())

    # ThreadPoolExecutor shutdown(wait=True) makes running tasks drain before
    # a raised failure can escape to a coordinator that might retry work.
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_inflight) as executor:
        try:
            while True:
                check_active()
                # In drain mode a deadline closes dispatch but existing Workers
                # still finish and receive durable Queue ACKs before aborting.
                if (drain_on_deadline and until is not None
                        and time.monotonic() >= until and not active):
                    raise RefillAborted("deadline_exceeded", snapshot())
                # A previously running Worker can fail WHILE another Worker's
                # acknowledgement is being processed. Never refill before
                # examining all already completed active Futures.
                for observed_future in tuple(active):
                    if observed_future.done():
                        if observed_future.cancelled():
                            raise RuntimeError("refill Worker was cancelled")
                        failure = observed_future.exception()
                        if failure is not None:
                            raise failure
                no_claim = False
                while len(active) < max_inflight:
                    check_active()
                    if (drain_on_deadline and until is not None
                            and time.monotonic() >= until):
                        no_claim = True
                        break
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
                    if (drain_on_deadline and until is not None
                            and time.monotonic() >= until):
                        raise RefillAborted("deadline_exceeded", snapshot())
                    if producer_done is None:
                        return snapshot()
                    if producer_done():
                        # Queue was empty at the earlier peek. Producer may
                        # have published its last TODO just before marking
                        # completion; do one authoritative final claim.
                        check_active()
                        if (drain_on_deadline and until is not None
                                and time.monotonic() >= until):
                            raise RefillAborted("deadline_exceeded", snapshot())
                        final_claim = claim_one()
                        if final_claim is None:
                            return snapshot()
                        if (not isinstance(final_claim, ClaimedWork)
                                or not isinstance(final_claim.receipt, str)
                                or not final_claim.receipt):
                            raise ValueError("claim requires nonempty receipt")
                        if final_claim.receipt in seen:
                            raise ValueError("replayed claim receipt")
                        seen.add(final_claim.receipt)
                        claimed += 1
                        future = executor.submit(run_worker, final_claim.item)
                        active[future] = final_claim
                        peak = max(peak, len(active))
                        continue
                    check_active()
                    time.sleep(empty_poll_seconds)
                    continue

                timeout = (empty_poll_seconds if until is None or drain_on_deadline
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
