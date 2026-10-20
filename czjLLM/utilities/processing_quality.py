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
_KNOWN_CODES = {
    "JSON_VALID", "JSON_SYNTAX_INVALID", "JSON_REPAIR_SUCCEEDED",
    "JSON_REPAIR_FAILED", "SCHEMA_MISSING_FIELD",
    "SCHEMA_TIME_PRECISION", "SCHEMA_EVENT_REFERENCE",
    "SCHEMA_OTHER", "WRITEBACK_CONFIRMED",
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
    if event not in _KNOWN_EVENTS or code not in _KNOWN_CODES:
        raise ValueError("unknown quality event/code")
    if scope not in {"slice", "document"}:
        raise ValueError("invalid quality scope")
    data = {
        "schema_version": 1,
        "event_id": uuid4().hex,
        "ts": datetime.now(timezone.utc).isoformat(),
        "run_id": str(run_id or "")[:96],
        "event": event,
        "scope": scope,
        "code": code,
        "outcome": str(outcome or "")[:32],
        "document_id": str(document_id or "")[:160],
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
        self._event_ids = set()
        self._codes = Counter()
        self._json_valid = 0
        self._json_invalid = 0
        self._repair_success = 0
        self._repair_failure = 0
        self._schema_rejected = set()
        self._writeback_confirmed = set()

    def add(self, record: dict) -> bool:
        if not isinstance(record, dict) or record.get("schema_version") != 1:
            return False
        event_id = record.get("event_id")
        event = record.get("event")
        code = record.get("code")
        if not isinstance(event_id, str) or not event_id or event in (None, ""):
            return False
        if event not in _KNOWN_EVENTS or code not in _KNOWN_CODES:
            return False
        if event_id in self._event_ids:
            return False
        self._event_ids.add(event_id)
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
        return True

    def snapshot(self) -> dict:
        validations = self._json_valid + self._json_invalid
        repairs = self._repair_success + self._repair_failure
        # Successful re-write can recover a previously rejected document.
        failed_docs = self._schema_rejected - self._writeback_confirmed
        decided = failed_docs | self._writeback_confirmed
        return {
            "events": len(self._event_ids),
            "slice_validation_attempts": validations,
            "slice_initial_invalid": self._json_invalid,
            "slice_initial_invalid_pct": round(100 * self._json_invalid / validations, 2) if validations else None,
            "repair_attempts": repairs,
            "repair_succeeded": self._repair_success,
            "repair_success_pct": round(100 * self._repair_success / repairs, 2) if repairs else None,
            "documents_decided": len(decided),
            "documents_schema_pending": len(failed_docs),
            "documents_writeback_confirmed": len(self._writeback_confirmed),
            "document_schema_reject_pct": round(100 * len(failed_docs) / len(decided), 2) if decided else None,
            "error_codes": dict(self._codes.most_common()),
        }


class QualityTailReader:
    """Incrementally parse complete JSONL lines; never block the Tk UI thread."""
    def __init__(self, path: str = ""):
        self.path = str(path or "")
        self.offset = 0
        self.accumulator = QualityAccumulator()

    def poll(self) -> tuple[bool, dict]:
        if not self.path:
            return False, self.accumulator.snapshot()
        try:
            size = os.path.getsize(self.path)
        except OSError:
            return False, self.accumulator.snapshot()
        if size < self.offset:
            self.offset = 0
            self.accumulator = QualityAccumulator()
        if size == self.offset:
            return False, self.accumulator.snapshot()
        changed = False
        try:
            with open(self.path, "rb") as fp:
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
                        parsed = json.loads(line.decode("utf-8"))
                    except (UnicodeDecodeError, ValueError):
                        continue
                    changed = self.accumulator.add(parsed) or changed
        except OSError:
            return False, self.accumulator.snapshot()
        return changed, self.accumulator.snapshot()
