"""Bounded, in-memory incremental CSV coverage for the visible GUI page.

No unbounded full-file read, queue access, DB/model calls, sidecars or raw
CSV fields in the return object. The UI only uses a projection once the
scanner has caught up with its *verified* observed file length.
"""
from __future__ import annotations

from collections import OrderedDict
import os
from pathlib import Path
import stat
import threading

from czjLLM.utilities.llm_failure_summary import (
    _audit_file_name, _iter_audit_csv_rows, _same_open_file,
    _snapshot_path_components, _verify_path_snapshot,
)

from czjLLM.job_manager.document_model_endpoint import (
    _MODEL_NAME, _audit_path_key, _endpoint_ip,
)

MAX_SCAN_BYTES = 4 * 1024 * 1024
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_CACHE_PAGES = 3
MAX_HEADER_FIELDS = 128
_CHECKPOINT_BYTES = 256
_REQUIRED = ("prompt_file", "model", "base_url")
_CACHE = OrderedDict()
_LOCK = threading.Lock()


def _page_key(path, item_dirs):
    normalized = tuple(sorted(
        (str(key), _audit_path_key(dirname))
        for key, dirname in item_dirs.items()
    ))
    return (str(Path(path)), normalized)


def _fresh_state(item_dirs):
    return {
        "offset": 0, "headers": None,
        "identity": None, "previous_size": None, "previous_mtime": None,
        "checkpoint": b"",
        "data": {
            str(k): {"latest": "", "pairs": [], "more_pairs": False}
            for k in item_dirs
        },
    }


def _open_checked(path):
    path = Path(path)
    # The previous bounded reader rejects *all* Windows junction/reparse
    # components, not just POSIX symlinks. Reuse that exact contract.
    if not _audit_file_name(path):
        raise ValueError("expected canonical llm_call_audit run filename")
    components = _snapshot_path_components(path)
    before = components[0][1]
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("audit must be a regular file")
    if before.st_size > MAX_FILE_BYTES:
        raise ValueError("audit exceeds supported incremental read budget")
    fd = os.open(
        path, os.O_RDONLY | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0),
    )
    try:
        opened = os.fstat(fd)
        if not _same_open_file(before, opened):
            raise ValueError("audit generation changed during open")
        _verify_path_snapshot(components)
        return fd, components
    except BaseException:
        os.close(fd)
        raise

def _read_at(fd, offset, size):
    os.lseek(fd, offset, os.SEEK_SET)
    return os.read(fd, size)


def _checkpoint(fd, offset):
    start = max(0, offset - _CHECKPOINT_BYTES)
    return _read_at(fd, start, offset - start)



def _complete_csv_records(text):
    """Yield newline-terminated logical CSV records, honoring quoted newlines.

    This lightweight quote tracker finds record boundaries only; actual CSV
    field validation uses the project's existing bounded custom parser.
    It does not modify Python's process-global csv.field_size_limit().
    """
    start = 0
    i = 0
    inside_quote = False
    field_start = True
    while i < len(text):
        c = text[i]
        if inside_quote:
            if c == '"':
                if i + 1 < len(text) and text[i + 1] == '"':
                    i += 2
                    continue
                inside_quote = False
            i += 1
            continue
        if c == '"' and field_start:
            inside_quote = True
            field_start = False
        elif c == ',':
            field_start = True
        elif c in "\r\n":
            if c == "\r" and i + 1 < len(text) and text[i + 1] == "\n":
                i += 1
            yield text[start:i + 1]
            start = i + 1
            field_start = True
        else:
            field_start = False
        i += 1


def _consume_csv(state, chunk, requested):
    """Commit only complete logical records; keep large fields privately."""
    end = chunk.rfind(b"\n")
    if end < 0:
        if len(chunk) >= MAX_SCAN_BYTES:
            raise ValueError("audit contains an oversized or incomplete CSV record")
        return 0
    text = chunk[:end + 1].decode("utf-8", errors="strict")
    consumed = 0
    for raw_record in _complete_csv_records(text):
        limit = [state.get("width", MAX_HEADER_FIELDS)]
        rows = list(_iter_audit_csv_rows(raw_record, field_limit=limit))
        if len(rows) != 1:
            raise ValueError("invalid audit CSV record")
        row = rows[0]
        consumed += len(raw_record.encode("utf-8"))
        if state["headers"] is None:
            if (not row or len(row) > MAX_HEADER_FIELDS
                    or len(row) != len(set(row))
                    or any(row.count(name) != 1 for name in _REQUIRED)):
                raise ValueError("audit CSV model/endpoint headers unavailable")
            state["headers"] = {name: row.index(name) for name in _REQUIRED}
            state["width"] = len(row)
            continue
        if len(row) != state["width"]:
            raise ValueError("audit CSV row width mismatch")
        indices = state["headers"]
        record = _audit_path_key(row[indices["prompt_file"]])
        model = row[indices["model"]]
        if not record or not _MODEL_NAME.fullmatch(model):
            continue
        endpoint = _endpoint_ip(row[indices["base_url"]])
        display = f"{model} · {endpoint or 'IP 未記錄'}"
        for key, directory in requested:
            if directory and record.startswith(directory + "/"):
                entry = state["data"][key]
                entry["latest"] = display
                pairs = entry["pairs"]
                if display not in pairs:
                    if len(pairs) < 6:
                        pairs.append(display)
                    else:
                        entry["more_pairs"] = True
    if consumed == 0 and len(chunk) >= MAX_SCAN_BYTES:
        raise ValueError("audit contains a CSV record beyond bounded chunk")
    return consumed

def read_incremental_model_endpoints(path: str | Path,
                                     item_dirs: dict[str, object]) -> dict:
    """Read at most 4 MiB per refresh for one 12-row page, with safe restart.

    No stale display: if scan is behind the observed file length, complete
    is False. On unexpected changes/invalid rows, discard cached evidence.
    """
    if len(item_dirs) > 100:
        raise ValueError("too many visible items")
    key = _page_key(path, item_dirs)
    requested = key[1]
    with _LOCK:
        state = _CACHE.get(key)
        if state is None:
            state = _fresh_state(item_dirs)
            _CACHE[key] = state
            if len(_CACHE) > MAX_CACHE_PAGES:
                _CACHE.popitem(last=False)
        _CACHE.move_to_end(key)
        fd = None
        try:
            fd, components = _open_checked(path)
            before = os.fstat(fd)
            identity = (before.st_dev, before.st_ino)
            if (state["identity"] is not None and (
                    identity != state["identity"]
                    or before.st_size < state["offset"]
                    or (state["previous_size"] == before.st_size
                        and state["previous_mtime"] != before.st_mtime_ns)
                    or _checkpoint(fd, state["offset"]) != state["checkpoint"])):
                state = _fresh_state(item_dirs)
                _CACHE[key] = state
            state["identity"] = identity
            pos = state["offset"]
            available = max(0, before.st_size - pos)
            chunk = _read_at(fd, pos, min(MAX_SCAN_BYTES, available))
            # Parsing mutates only cached *aggregates*, never source data.
            advanced = _consume_csv(state, chunk, requested)
            state["offset"] += advanced
            state["checkpoint"] = _checkpoint(fd, state["offset"])
            after = os.fstat(fd)
            _verify_path_snapshot(components)
            check_path = components[0][0].lstat()
            if ((after.st_dev, after.st_ino) != identity
                    or not _same_open_file(check_path, before)
                    # An in-place rewrite or append while scanning can make
                    # aggregates refer to different bytes than the checkpoint.
                    # Invalidate, never certify such a mixed generation.
                    or after.st_size != before.st_size
                    or after.st_mtime_ns != before.st_mtime_ns
                    or after.st_size < state["offset"]):
                raise ValueError("audit changed generation during incremental read")
            state["previous_size"] = after.st_size
            state["previous_mtime"] = after.st_mtime_ns
            complete = (
                state["headers"] is not None
                and state["offset"] == after.st_size
                and after.st_size == before.st_size
                and after.st_mtime_ns == before.st_mtime_ns
            )
            # Copy bounded presentation objects so callers cannot mutate cache.
            values = {
                k: {"latest": v["latest"], "pairs": list(v["pairs"]),
                    "more_pairs": v["more_pairs"]}
                for k, v in state["data"].items()
            }
            return {
                "complete": complete, "scanned_bytes": state["offset"],
                "total_bytes": after.st_size, "models": values,
            }
        except (OSError, ValueError, UnicodeError):
            _CACHE.pop(key, None)
            raise
        finally:
            if fd is not None:
                os.close(fd)
