"""Count only bounded, explicit per-run Queue Meter receipts.

Observational evidence only: terminal row status is not a Worker ACK, source
cleanup permission, or durable SQL/ES writeback receipt.
"""
from __future__ import annotations

TERMINAL_STATES = frozenset({
    "merged", "writeback_failed_schema", "writeback_failed",
    "cancelled", "failed",
})
MAX_ROWS = 100_000
MAX_COUNT = 1_000_000_000


def _count(value):
    return value if type(value) is int and 0 <= value <= MAX_COUNT else None


def summarize_meter(meter):
    """Return fixed-schema, aggregate-only evidence; never disclose row keys."""
    if not isinstance(meter, dict):
        raise ValueError("invalid meter")
    rows = meter.get("rows")
    queue = meter.get("queue")
    if not isinstance(rows, dict) or not isinstance(queue, dict):
        raise ValueError("invalid meter structure")
    if len(rows) > MAX_ROWS:
        raise ValueError("meter row budget exceeded")

    queue_counts = {
        name: _count(queue.get(name))
        for name in ("pending", "running", "completed")
    }
    counts = {
        "total_rows": len(rows),
        "settled_rows": 0,
        "outstanding_rows": 0,
        "unknown_receipt_rows": 0,
        "terminal_rows_with_outstanding_receipts": 0,
        "terminal_rows_with_unknown_receipts": 0,
        "terminal_running_receipts": 0,
        "terminal_pending_receipts": 0,
        "observed_row_running_receipts": 0,
        "observed_row_pending_receipts": 0,
    }

    for row in rows.values():
        state = row.get("status") if isinstance(row, dict) else None
        terminal = type(state) is str and state in TERMINAL_STATES
        pending = _count(row.get("queue_pending")) if isinstance(row, dict) else None
        running = _count(row.get("queue_running")) if isinstance(row, dict) else None
        if pending is None or running is None:
            counts["unknown_receipt_rows"] += 1
            if terminal:
                counts["terminal_rows_with_unknown_receipts"] += 1
            continue

        counts["observed_row_running_receipts"] += running
        counts["observed_row_pending_receipts"] += pending
        if pending == running == 0:
            counts["settled_rows"] += 1
        else:
            counts["outstanding_rows"] += 1
            if terminal:
                counts["terminal_rows_with_outstanding_receipts"] += 1
                counts["terminal_running_receipts"] += running
                counts["terminal_pending_receipts"] += pending

    global_running_without_row = (
        queue_counts["running"] is not None
        and queue_counts["running"] > 0
        and counts["observed_row_running_receipts"] == 0
    )
    incomplete = (
        counts["unknown_receipt_rows"] > 0
        or any(value is None for value in queue_counts.values())
    )
    candidate = (
        counts["terminal_rows_with_outstanding_receipts"] > 0
        or global_running_without_row
    )
    if candidate:
        status = "REVIEW_REQUIRED"
    elif incomplete:
        status = "INCOMPLETE_EVIDENCE"
    else:
        status = "OBSERVED_NOT_PROVEN"
    return {
        "schema_version": 1,
        "status": status,
        "source": "EXPLICIT_RUN_METER",
        "queue": queue_counts,
        "row_receipts": counts,
        "signals": (
            (["TERMINAL_STATUS_WITH_OUTSTANDING_RECEIPT"]
             if counts["terminal_rows_with_outstanding_receipts"] else [])
            + (["GLOBAL_RUNNING_WITHOUT_OBSERVED_ROW_RUNNING"]
               if global_running_without_row else [])
            + (["MISSING_OR_INVALID_RECEIPT_EVIDENCE"]
               if incomplete else [])
        ),
        "gpu_utilization": "NOT_MEASURED",
        "sink_readback": "NOT_MEASURED",
        "safety": "READ_ONLY_NO_ACK_NO_REPLAY_NO_CLEANUP",
        "snapshot_limitation": "NON_ATOMIC_UNAUTHENTICATED_METER",
    }
