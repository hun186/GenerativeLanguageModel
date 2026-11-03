"""Bounded, per-adapter console summaries for repeated ES output checks.

This is diagnostic-only: never changes an ES pending decision, the validation
criteria, or which documents are selected for LLM processing.
"""
from __future__ import annotations

import hashlib
import threading


_MAX_SIGNATURES = 32
_INIT_LOCK = threading.Lock()


def _safe_component(value: object) -> tuple[str, str]:
    """Bound console output and stored key; suppress newline/control injection."""
    raw = str(value)
    encoded = raw.encode("utf-8", errors="replace")
    signature = hashlib.sha256(encoded).hexdigest()[:16]
    display = "".join(ch if ch.isprintable() and ch not in "\r\n" else "?" for ch in raw)
    if len(display) > 160:
        display = display[:157] + "..."
    return display, signature


class RequiredOutputFailureSummary:
    """Counts rule failures (check events, NOT distinct documents).

    Each adapter retains at most 32 distinct rule signatures. The console
    emits the first occurrence, checkpoints 10/100/1000 and every 10k, plus
    exact grouped totals when the pending scan finishes or closes.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[tuple[str, ...], list] = {}
        self._other = 0
        self._overflow_notified = False

    def record(self, *, path: object, validator: object, fmt: object,
               found_valid: int, min_valid_count: int) -> None:
        values = (path, validator, fmt, found_valid, min_valid_count)
        safe = tuple(_safe_component(value) for value in values)
        key = tuple(item[1] for item in safe)
        shown = tuple(item[0] for item in safe)
        message = None
        with self._lock:
            entry = self._counts.get(key)
            if entry is None:
                if len(self._counts) == _MAX_SIGNATURES:
                    self._other += 1
                    if not self._overflow_notified:
                        self._overflow_notified = True
                        message = (
                            "[DEBUG] required_output_check: more than 32 "
                            "distinct failure signatures; additional signatures "
                            "are aggregated without logging their details"
                        )
                else:
                    entry = [shown, 0]
                    self._counts[key] = entry
            if entry is not None:
                entry[1] += 1
                n = entry[1]
                details = (
                    f"path={shown[0]}, validator={shown[1]}, "
                    f"format={shown[2]}, found_valid={shown[3]}, "
                    f"min_valid_count={shown[4]}"
                )
                if n == 1:
                    message = (
                        f"[DEBUG] required_output_check failed: {details} "
                        "(first occurrence; repeats summarized)"
                    )
                elif n in (10, 100, 1000) or (n > 1000 and n % 10000 == 0):
                    message = (
                        f"[DEBUG] required_output_check repeated: "
                        f"occurrences={n:,}, {details}"
                    )
        if message:
            print(message, flush=True)

    def flush(self) -> None:
        """Print completed/partial scan totals, then start a new time window."""
        with self._lock:
            snapshot = [(tuple(record[0]), record[1]) for record in self._counts.values()]
            other = self._other
            self._counts = {}
            self._other = 0
            self._overflow_notified = False
        for fields, count in snapshot:
            print(
                "[DEBUG] required_output_check summary: "
                f"occurrences={count:,}, path={fields[0]}, "
                f"validator={fields[1]}, format={fields[2]}, "
                f"found_valid={fields[3]}, min_valid_count={fields[4]} "
                "(validation events; not distinct documents)",
                flush=True,
            )
        if other:
            print(
                "[DEBUG] required_output_check summary: "
                f"additional_signatures_occurrences={other:,} "
                "(bounded signature cardinality)",
                flush=True,
            )


def _get_reporter(owner: object) -> RequiredOutputFailureSummary:
    existing = getattr(owner, "_required_output_failure_reporter", None)
    if existing is not None:
        return existing
    with _INIT_LOCK:
        existing = getattr(owner, "_required_output_failure_reporter", None)
        if existing is None:
            existing = RequiredOutputFailureSummary()
            setattr(owner, "_required_output_failure_reporter", existing)
    return existing


def record_required_output_failure(owner: object, *, path: object,
                                   validator: object, fmt: object,
                                   found_valid: int, min_valid_count: int) -> None:
    _get_reporter(owner).record(
        path=path, validator=validator, fmt=fmt,
        found_valid=found_valid, min_valid_count=min_valid_count,
    )


def flush_required_output_failures(owner: object) -> None:
    reporter = getattr(owner, "_required_output_failure_reporter", None)
    if reporter is not None:
        reporter.flush()
