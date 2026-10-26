"""Optional temporary SQLite identity index for exact offline quality reports.

SQLite stores raw event/document identities in a *private temporary directory*
for the lifetime of a single report only. This does not implement a durable
checkpoint, automatic retention, or a physical process-RSS limit. No existing
audit JSONL, archive, or manifest is mutated.
"""
from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import tempfile

from czjLLM.utilities.processing_quality import QualityAccumulator


def _execute(connection: sqlite3.Connection, query: str, parameters=()):
    """Prevent private temporary paths/identities leaking into CLI errors."""
    try:
        return connection.execute(query, parameters)
    except sqlite3.Error:
        raise ValueError("temporary quality identity index unavailable") from None


class _Signatures:
    def __init__(self, connection: sqlite3.Connection):
        self._db = connection

    def __contains__(self, event_id: str) -> bool:
        return _execute(
            self._db, "SELECT 1 FROM signatures WHERE id=?", (event_id,)
        ).fetchone() is not None

    def __len__(self) -> int:
        return _execute(self._db, "SELECT COUNT(*) FROM signatures").fetchone()[0]

    def __getitem__(self, event_id: str) -> bytes:
        row = _execute(
            self._db, "SELECT digest FROM signatures WHERE id=?", (event_id,)
        ).fetchone()
        if row is None:
            raise KeyError(event_id)
        return row[0]

    def __setitem__(self, event_id: str, signature: bytes) -> None:
        _execute(
            self._db, "INSERT INTO signatures(id, digest) VALUES (?, ?)",
            (event_id, signature),
        )


class _Identities:
    def __init__(self, connection: sqlite3.Connection, table: str):
        if table not in ("rejected", "confirmed"):
            raise ValueError("invalid quality identity table")
        self._db = connection
        self._table = table

    def __contains__(self, doc_id: str) -> bool:
        return _execute(
            self._db, f"SELECT 1 FROM {self._table} WHERE id=?", (doc_id,)
        ).fetchone() is not None

    def __len__(self) -> int:
        return _execute(
            self._db, f"SELECT COUNT(*) FROM {self._table}"
        ).fetchone()[0]

    def add(self, doc_id: str) -> None:
        _execute(
            self._db, f"INSERT OR IGNORE INTO {self._table}(id) VALUES (?)",
            (doc_id,),
        )


class DiskBackedQualityAccumulator(QualityAccumulator):
    """Exact per-report dedup/decision sets spilled to ephemeral SQLite.

    This is an opt-in *offline-only* backend. It must not be reused by Tk GUI
    polling, producers, or durable archive lifecycle operations. close() is
    required (prefer with), including on every error path.
    """

    def __init__(self):
        super().__init__()
        self._tmp = tempfile.TemporaryDirectory(prefix="czjllm-quality-")
        self._db = None
        try:
            db_path = Path(self._tmp.name) / "identities.sqlite3"
            fd = os.open(db_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
            self._db = sqlite3.connect(str(db_path))
            _execute(self._db, "PRAGMA cache_size=-1024")
            _execute(self._db, "PRAGMA temp_store=FILE")
            self._db.executescript(
                "CREATE TABLE signatures (id TEXT PRIMARY KEY COLLATE BINARY, digest BLOB NOT NULL);"
                "CREATE TABLE rejected (id TEXT PRIMARY KEY COLLATE BINARY);"
                "CREATE TABLE confirmed (id TEXT PRIMARY KEY COLLATE BINARY);"
            )
            self._event_signatures = _Signatures(self._db)
            self._schema_rejected = _Identities(self._db, "rejected")
            self._writeback_confirmed = _Identities(self._db, "confirmed")
        except (OSError, sqlite3.Error, ValueError):
            self.close()
            raise ValueError("temporary quality identity index unavailable") from None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        if self._db is not None:
            self._db.close()
            self._db = None
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None

    def empty_copy(self):
        # A source that changed beneath a one-shot offline report must never
        # silently reset the exact accumulator and return a partial history.
        raise ValueError("quality source changed during disk-backed reporting")

    def snapshot(self) -> dict:
        if self._db is None:
            raise ValueError("temporary quality identity index unavailable")
        validations = self._json_valid + self._json_invalid
        repairs = self._repair_success + self._repair_failure
        pending = _execute(
            self._db,
            "SELECT COUNT(*) FROM rejected AS r "
            "WHERE NOT EXISTS (SELECT 1 FROM confirmed AS c WHERE c.id=r.id)",
        ).fetchone()[0]
        confirmed = len(self._writeback_confirmed)
        decided = pending + confirmed
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
            "documents_decided": decided,
            "documents_schema_pending": pending,
            "documents_writeback_confirmed": confirmed,
            "document_schema_reject_pct": round(100 * pending / decided, 2) if decided else None,
            "error_codes": dict(self._codes.most_common()),
        }
