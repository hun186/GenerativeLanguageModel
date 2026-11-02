"""Bounded, in-memory incremental CSV coverage for the visible GUI page.

No unbounded full-file read, queue access, DB/model calls, sidecars or raw
CSV fields in the return object. The UI only uses a projection once the
scanner has caught up with its *verified* observed file length.
"""
from __future__ import annotations

from collections import OrderedDict
import csv
import io
import os
from pathlib import Path
import stat
import threading

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
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("untrusted audit path")
    before = path.lstat()
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
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError("audit changed file type")
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("audit generation changed during open")
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError("audit path redirected")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read_at(fd, offset, size):
    os.lseek(fd, offset, os.SEEK_SET)
    return os.read(fd, size)


def _checkpoint(fd, offset):
    start = max(0, offset - _CHECKPOINT_BYTES)
    return _read_at(fd, start, offset - start)


def _consume_csv(state, chunk, requested):
    """Only commit parser-complete rows. UTF-8/CSV exceptions fail closed."""
    end = chunk.rfind(b"\n")
    if end < 0:
        if len(chunk) >= MAX_SCAN_BYTES:
            raise ValueError("audit contains an oversized or incomplete CSV record")
        return 0
    text = chunk[:end + 1].decode("utf-8", errors="strict")
    stream = io.StringIO(text, newline="")
    rows = csv.reader(stream, strict=True)
    consumed = 0
    previous_char = 0
    while True:
        try:
            row = next(rows)
        except StopIteration:
            break
        except csv.Error as exc:
            # A chunk can end in a quoted multiline CSV record; retry the
            # uncommitted suffix next refresh. Other parser errors fail closed.
            if str(exc) == "unexpected end of data":
                break
            raise ValueError("invalid audit CSV record") from exc
        current_char = stream.tell()
        consumed += len(text[previous_char:current_char].encode("utf-8"))
        previous_char = current_char
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
            fd = _open_checked(path)
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
            check_path = Path(path).lstat()
            if ((after.st_dev, after.st_ino) != identity
                    or (check_path.st_dev, check_path.st_ino) != identity
                    or after.st_size < state["offset"]
                    or any(p.is_symlink() for p in (Path(path), *Path(path).parents))):
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
        except (OSError, ValueError, UnicodeError, csv.Error):
            _CACHE.pop(key, None)
            raise
        finally:
            if fd is not None:
                os.close(fd)
