"""Bounded append-only audit scanning for the local monitoring process.

Uses the existing canonical path/reparse checks, CSV record framing, and
shared numeric accumulator. Never publishes partial totals as observed.
"""
import csv
import io
import os
from copy import deepcopy

from czjLLM.job_manager.audit_distribution import AuditAccumulator, project_public_audit
from czjLLM.job_manager.document_model_endpoint_incremental import (
    _open_checked, _read_at, _checkpoint, _complete_csv_records,
)
from czjLLM.utilities.llm_failure_summary import _same_open_file, _verify_path_snapshot

MAX_SCAN_BYTES = 4 * 1024 * 1024
MAX_ROWS = 200000
MAX_GROUPS = 4096
MAX_HEADER_FIELDS = 128


class IncrementalAuditReader:
    """Single-owner scanner with bounded reads and exact retained samples."""

    def __init__(self):
        self.path = None
        self._reset()

    def _reset(self):
        self.offset = 0
        self.headers = None
        self.identity = None
        self.previous_size = self.previous_mtime = None
        self.checkpoint = b""
        self.acc = AuditAccumulator(max_rows=MAX_ROWS, max_groups=MAX_GROUPS)
        self.cached = None

    def _rows(self, chunk):
        end = chunk.rfind(b"\n")
        if end < 0:
            if len(chunk) >= MAX_SCAN_BYTES:
                raise ValueError("audit record exceeds scan budget")
            return
        text = chunk[:end + 1].decode("utf-8", errors="strict")
        advanced = 0
        for record in _complete_csv_records(text):
            parsed = list(csv.reader(io.StringIO(record, newline=""), strict=True))
            if len(parsed) != 1:
                raise ValueError("invalid audit record")
            row = parsed[0]
            advanced += len(record.encode("utf-8"))
            self.offset += len(record.encode("utf-8"))
            if self.headers is None:
                if (not row or len(row) > MAX_HEADER_FIELDS or len(set(row)) != len(row)
                        or not {"ok", "prompt_file", "token_usage_source"}.issubset(row)):
                    raise ValueError("invalid audit header")
                self.headers = row
            else:
                if len(row) != len(self.headers):
                    raise ValueError("invalid audit width")
                yield dict(zip(self.headers, row))
        if not advanced and len(chunk) >= MAX_SCAN_BYTES:
            raise ValueError("logical record exceeds scan budget")

    def read(self, path):
        if not path:
            self.path = None
            self._reset()
            return {"status": "waiting_for_audit"}
        if path != self.path:
            self.path = path
            self._reset()
        fd = None
        try:
            fd, components = _open_checked(path)
            before = os.fstat(fd)
            identity = (before.st_dev, before.st_ino)
            if self.identity is not None and (
                    identity != self.identity or before.st_size < self.offset
                    or (before.st_size == self.previous_size
                        and before.st_mtime_ns != self.previous_mtime)
                    or _checkpoint(fd, self.offset) != self.checkpoint):
                self._reset()
            self.identity = identity
            previous = self.offset
            available = before.st_size - self.offset
            chunk = _read_at(fd, self.offset, min(MAX_SCAN_BYTES, available))
            self.acc.consume(self._rows(chunk), strict=True)
            self.checkpoint = _checkpoint(fd, self.offset)
            after = os.fstat(fd)
            _verify_path_snapshot(components)
            if ((after.st_dev, after.st_ino) != identity
                    or not _same_open_file(components[0][0].lstat(), before)
                    or after.st_size != before.st_size
                    or after.st_mtime_ns != before.st_mtime_ns):
                raise ValueError("audit changed during scan")
            self.previous_size, self.previous_mtime = after.st_size, after.st_mtime_ns
            if self.headers is None or self.offset != after.st_size:
                self.cached = None
                return {"status": "catching_up", "scanned_bytes": self.offset,
                        "total_bytes": after.st_size}
            if self.cached is None or self.offset != previous:
                self.cached = project_public_audit(self.acc.snapshot())
                self.cached["scope"] = "bounded_incremental_current_audit"
            return deepcopy(self.cached)
        except FileNotFoundError:
            self._reset()
            return {"status": "waiting_for_audit"}
        except (OSError, ValueError, UnicodeError, csv.Error, OverflowError):
            self._reset()
            return {"status": "unavailable_or_over_budget"}
        finally:
            if fd is not None:
                os.close(fd)
