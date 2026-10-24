# -*- coding: utf-8 -*-
"""Run-scoped, non-payload quality events for LLM/Row Merger observability.

Counters are intentionally separated by *slice attempts* and distinct document
IDs.  A repaired JSON response is not counted as a failed document.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import threading
from uuid import uuid4

_WRITE_LOCK = threading.Lock()
_KNOWN_EVENTS = {
    "slice_json_validation", "slice_json_repair",
    "document_schema_rejected", "document_writeback_confirmed",
}
_EVENT_CODES = {
    "slice_json_validation": {"JSON_VALID", "JSON_SYNTAX_INVALID"},
    "slice_json_repair": {"JSON_REPAIR_SUCCEEDED", "JSON_REPAIR_FAILED"},
    "document_schema_rejected": {
        "SCHEMA_MISSING_FIELD", "SCHEMA_TIME_PRECISION",
        "SCHEMA_EVENT_REFERENCE", "SCHEMA_OTHER",
    },
    "document_writeback_confirmed": {"WRITEBACK_CONFIRMED"},
    "consumer_orchestration_failure": {
        "CONSUMER_ROUND_TIMEOUT", "CONSUMER_ROUND_EXCEPTION",
        "CONSUMER_TERMINATED",
    },
    "row_merger_retryable_failure": {
        "ROW_MERGER_PREPARE_RETRY", "ROW_MERGER_WRITEBACK_RETRY",
    },
    "producer_operational_failure": {
        "PRODUCER_SCHEDULE_EXCEPTION", "PRODUCER_BACKPRESSURE_EXCEPTION",
        "PRODUCER_FUTURE_EXCEPTION",
    },
    "stage_orchestration_failure": {
        "STAGE_PREPARE_EXCEPTION", "STAGE_RUNNER_EXCEPTION",
    },
    "worker_phase_failure": {
        "WORKER_PRECALL_EXCEPTION", "WORKER_LLM_CALL_EXCEPTION",
        "WORKER_RESPONSE_EXCEPTION", "WORKER_PERSIST_EXCEPTION",
        "WORKER_LLM_TIMEOUT_EXCEPTION", "WORKER_LLM_CONNECTION_EXCEPTION",
        "WORKER_LLM_RATE_LIMIT_EXCEPTION",
        "WORKER_LLM_HTTP_SERVER_EXCEPTION", "WORKER_LLM_HTTP_CLIENT_EXCEPTION",
        "WORKER_LLM_RESPONSE_VALIDATION_EXCEPTION",
    },
}
_KNOWN_CODES = set().union(*_EVENT_CODES.values())
_EVENT_SCOPES = {
    event: ("document" if event.startswith("document_") else
            "run" if event in {
                "consumer_orchestration_failure", "row_merger_retryable_failure",
                "producer_operational_failure", "stage_orchestration_failure",
                "worker_phase_failure",
            } else "slice")
    for event in _EVENT_CODES
}
# Single source of truth for run-only diagnostic allowlists. Never classify
# slice/document codes as operational incidents in report drilldowns.
RUN_INCIDENT_CODES = {
    event: frozenset(_EVENT_CODES[event])
    for event in _EVENT_CODES if _EVENT_SCOPES[event] == "run"
}


def quality_event_path(audit_path: str) -> Path | None:
    """Pair this log with one existing per-run LLM audit, never all runs."""
    if not audit_path:
        return None
    source = Path(audit_path)
    name = source.stem
    if name.startswith("llm_call_audit_"):
        name = name[len("llm_call_audit_"):]
    return source.with_name(f"processing_quality_events_{name}.jsonl")


def classify_schema_error(message: str) -> str:
    text = str(message or "").lower()
    if "requires a date-only time_iso" in text or ("precision=" in text and "time_iso" in text):
        return "SCHEMA_TIME_PRECISION"
    if "is required by the current schema" in text or "required field" in text:
        return "SCHEMA_MISSING_FIELD"
    if "event_ids" in text or "reference" in text:
        return "SCHEMA_EVENT_REFERENCE"
    return "SCHEMA_OTHER"


def _lock_stream(lock_fp):
    if os.name == "nt":
        import msvcrt
        lock_fp.seek(0)
        msvcrt.locking(lock_fp.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl
        fcntl.flock(lock_fp.fileno(), fcntl.LOCK_EX)


def _unlock_stream(lock_fp):
    if os.name == "nt":
        import msvcrt
        lock_fp.seek(0)
        msvcrt.locking(lock_fp.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(lock_fp.fileno(), fcntl.LOCK_UN)


def emit_quality_event(
    audit_path: str, *, run_id: str = "", event: str, code: str,
    scope: str, outcome: str, document_id: str = "", slice_id: str = "",
) -> Path | None:
    """Append a bounded, privacy-minimal record. Never include raw LLM output."""
    path = quality_event_path(audit_path)
    if path is None:
        return None
    if event not in _EVENT_CODES or code not in _EVENT_CODES[event]:
        raise ValueError("unknown or mismatched quality event/code")
    if scope != _EVENT_SCOPES[event]:
        raise ValueError("mismatched quality event scope")
    if scope == "run" and (
            document_id != "" or slice_id != ""):
        raise ValueError("run-scoped quality events cannot carry document or slice identities")
    data = {
        "schema_version": 1,
        "event_id": uuid4().hex,
        "ts": datetime.now(timezone.utc).isoformat(),
        "run_id": str(run_id or "")[:96],
        "event": event,
        "scope": scope,
        "code": code,
        "outcome": str(outcome or "")[:32],
        "document_id": str(document_id or ""),
        "slice_id": Path(str(slice_id)).name[:160] if slice_id else "",
    }
    # Long SQL/ES keys must retain distinct identities even with shared prefixes.
    # Store a stable bounded fingerprint instead of silently merging documents.
    if len(data["document_id"]) > 160:
        data["document_id"] = "sha256:" + hashlib.sha256(
            data["document_id"].encode("utf-8", errors="surrogatepass")
        ).hexdigest()
    payload = (json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with _WRITE_LOCK:
        with lock_path.open("a+b") as lock_fp:
            if lock_fp.seek(0, os.SEEK_END) == 0:
                lock_fp.write(b"0")
                lock_fp.flush()
            _lock_stream(lock_fp)
            try:
                with path.open("ab") as fp:
                    fp.write(payload)
            finally:
                _unlock_stream(lock_fp)
    return path


class QualityAccumulator:
    """Aggregate event attempts and distinct documents without mixing units."""
    def __init__(self):
        self._event_signatures = {}
        self._codes = Counter()
        self._json_valid = 0
        self._json_invalid = 0
        self._repair_success = 0
        self._repair_failure = 0
        self._consumer_failures = 0
        self._row_merger_retryable_failures = 0
        self._producer_operational_failures = 0
        self._stage_orchestration_failures = 0
        self._worker_phase_failures = 0
        self._schema_rejected = set()
        self._writeback_confirmed = set()

    def add(self, record: dict) -> bool:
        if not isinstance(record, dict) or type(record.get("schema_version")) is not int:
            return False
        if record["schema_version"] != 1:
            return False
        event_id = record.get("event_id")
        event = record.get("event")
        code = record.get("code")
        if not isinstance(event_id, str) or not event_id.strip():
            return False
        if not isinstance(event, str) or event not in _EVENT_CODES:
            return False
        if not isinstance(code, str) or code not in _EVENT_CODES[event]:
            return False
        # Old fixtures may omit scope entirely; explicit null is invalid.
        if "scope" in record and record["scope"] != _EVENT_SCOPES[event]:
            return False
        if _EVENT_SCOPES[event] == "run" and (
                record.get("document_id", "") != "" or
                record.get("slice_id", "") != ""):
            # Defensive read boundary: reject preexisting/tampered JSONL identities.
            return False
        if event.startswith("document_") and not (
                isinstance(record.get("document_id"), str) and record["document_id"].strip()):
            return False
        if event_id in self._event_signatures:
            return False
        try:
            signature = hashlib.sha256(json.dumps(
                record, sort_keys=True, ensure_ascii=False,
                separators=(",", ":"), allow_nan=False,
            ).encode("utf-8")).digest()
        except (TypeError, ValueError, UnicodeError, RecursionError):
            # An in-process non-JSON record is not an auditable event.
            return False
        self._event_signatures[event_id] = signature
        if event == "slice_json_validation":
            if code == "JSON_VALID":
                self._json_valid += 1
            elif code == "JSON_SYNTAX_INVALID":
                self._json_invalid += 1
                self._codes[code] += 1
        elif event == "slice_json_repair":
            if code == "JSON_REPAIR_SUCCEEDED":
                self._repair_success += 1
            elif code == "JSON_REPAIR_FAILED":
                self._repair_failure += 1
                self._codes[code] += 1
        elif event == "document_schema_rejected":
            doc = record.get("document_id")
            if isinstance(doc, str) and doc:
                self._schema_rejected.add(doc)
                self._codes[code] += 1
        elif event == "document_writeback_confirmed":
            doc = record.get("document_id")
            if isinstance(doc, str) and doc:
                self._writeback_confirmed.add(doc)
        elif event == "consumer_orchestration_failure":
            # Retry observations are not failed calls, slices, or documents.
            self._consumer_failures += 1
            self._codes[code] += 1
        elif event == "row_merger_retryable_failure":
            # Throttled run-scoped retry observations, never document decisions.
            self._row_merger_retryable_failures += 1
            self._codes[code] += 1
        elif event == "producer_operational_failure":
            # Producer catch-site incidents, not failed slices or documents.
            self._producer_operational_failures += 1
            self._codes[code] += 1
        elif event == "stage_orchestration_failure":
            # Stage control-plane exceptions, not provider or document rates.
            self._stage_orchestration_failures += 1
            self._codes[code] += 1
        elif event == "worker_phase_failure":
            # Captured leaf Worker phase exceptions, not failed API requests.
            self._worker_phase_failures += 1
            self._codes[code] += 1
        return True

    def is_identical_accepted_event(self, record: object) -> bool:
        """Only exact logical replays are duplicates; reused IDs with edits degrade."""
        if not isinstance(record, dict):
            return False
        event_id = record.get("event_id")
        if not isinstance(event_id, str) or event_id not in self._event_signatures:
            return False
        try:
            signature = hashlib.sha256(json.dumps(
                record, sort_keys=True, ensure_ascii=False,
                separators=(",", ":"), allow_nan=False,
            ).encode("utf-8")).digest()
        except (TypeError, ValueError, UnicodeError, RecursionError):
            return False
        return signature == self._event_signatures[event_id]

    def snapshot(self) -> dict:
        validations = self._json_valid + self._json_invalid
        repairs = self._repair_success + self._repair_failure
        # Successful re-write can recover a previously rejected document.
        failed_docs = self._schema_rejected - self._writeback_confirmed
        decided = failed_docs | self._writeback_confirmed
        return {
            "events": len(self._event_signatures),
            "slice_validation_attempts": validations,
            "slice_initial_invalid": self._json_invalid,
            "slice_initial_invalid_pct": round(100 * self._json_invalid / validations, 2) if validations else None,
            "repair_attempts": repairs,
            "repair_succeeded": self._repair_success,
            "consumer_orchestration_failure_events": self._consumer_failures,
            "row_merger_retryable_failure_events": self._row_merger_retryable_failures,
            "producer_operational_failure_events": self._producer_operational_failures,
            "stage_orchestration_failure_events": self._stage_orchestration_failures,
            "worker_phase_failure_events": self._worker_phase_failures,
            "repair_success_pct": round(100 * self._repair_success / repairs, 2) if repairs else None,
            "documents_decided": len(decided),
            "documents_schema_pending": len(failed_docs),
            "documents_writeback_confirmed": len(self._writeback_confirmed),
            "document_schema_reject_pct": round(100 * len(failed_docs) / len(decided), 2) if decided else None,
            "error_codes": dict(self._codes.most_common()),
        }


def _reject_nonstandard_json_constant(value: str):
    """Strict JSON excludes NaN, Infinity and -Infinity (Python accepts by default)."""
    raise ValueError("non-standard JSON constant")


class QualityTailReader:
    """Incrementally parse complete JSONL lines; never block the Tk UI thread.

    A same-path file may be rotated/replaced between polls. Besides its size and
    inode, check bounded fingerprints of previously consumed head/tail bytes.
    This detects in-place truncate+rewrite even after it regrows past offset,
    without rereading a potentially large historical stream each GUI tick.
    """
    _FINGERPRINT_BYTES = 512

    def __init__(self, path: str = ""):
        self.path = str(path or "")
        self.offset = 0
        self.accumulator = QualityAccumulator()
        self.skipped_corrupt_lines = 0
        self._file_identity = None
        self._committed_head = b""
        self._committed_tail = b""

    def _reset(self) -> None:
        self.offset = 0
        self.accumulator = QualityAccumulator()
        self.skipped_corrupt_lines = 0
        self._file_identity = None
        self._committed_head = b""
        self._committed_tail = b""

    def _fingerprints(self, fp, offset: int) -> tuple[bytes, bytes]:
        if offset <= 0:
            return b"", b""
        span = min(offset, self._FINGERPRINT_BYTES)
        fp.seek(0)
        head = fp.read(span)
        fp.seek(offset - span)
        tail = fp.read(span)
        return head, tail

    def poll(self) -> tuple[bool, dict]:
        if not self.path:
            return False, self.accumulator.snapshot()
        try:
            with open(self.path, "rb") as fp:
                stat = os.fstat(fp.fileno())
                identity = (stat.st_dev, stat.st_ino)
                size = stat.st_size
                reset = False
                if self._file_identity is not None:
                    if (identity != self._file_identity or size < self.offset
                            or self._fingerprints(fp, self.offset) != (
                                self._committed_head, self._committed_tail)):
                        # Existing offset no longer points into the same input
                        # generation; a size-only check misses fast rewrites.
                        self._reset()
                        reset = True
                if size == self.offset:
                    self._file_identity = identity
                    return reset, self.accumulator.snapshot()
                changed = reset
                fp.seek(self.offset)
                while True:
                    line = fp.readline()
                    if not line:
                        break
                    if not line.endswith(b"\n"):
                        # In-progress writer; retry the entire line next poll.
                        break
                    self.offset = fp.tell()
                    try:
                        parsed = json.loads(
                            line.decode("utf-8"),
                            parse_constant=_reject_nonstandard_json_constant,
                        )
                    except (UnicodeDecodeError, ValueError, RecursionError):
                        # A deeply nested complete line is corrupt input, not
                        # a reason to abort polling or lose all later events.
                        self.skipped_corrupt_lines += 1
                        continue
                    if self.accumulator.add(parsed):
                        changed = True
                    elif not self.accumulator.is_identical_accepted_event(parsed):
                        # Syntactically valid JSON can still be unsupported
                        # as a quality event (schema, missing ID, bad code).
                        self.skipped_corrupt_lines += 1
                self._file_identity = identity
                self._committed_head, self._committed_tail = self._fingerprints(
                    fp, self.offset)
                return changed, self.accumulator.snapshot()
        except OSError:
            return False, self.accumulator.snapshot()
