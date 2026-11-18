# -*- coding: utf-8 -*-
"""Private, bounded, session-only JSON repair inspection for Windows GUI.

Raw pairs never enter routine Quality/Audit/Queue logs or project directories.
Workers and the GUI are separate processes: the worker-side callback sends to
a dedicated bounded IPC queue, and ONLY the GUI process owns this FIFO.
Linux/headless execution does not install a sink and keeps no raw history.
"""
from __future__ import annotations

from collections import OrderedDict
import threading
from typing import Callable
from uuid import UUID

MAX_CASES = 50
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_PAIR_BYTES = 512 * 1024
MAX_TEXT_CHARS = 80_000
MAX_PENDING_IPC = 8

_sink_lock = threading.Lock()
_gui_sink: Callable[[str, str, str, str], bool] | None = None


def set_gui_repair_sink(sink: Callable[[str, str, str, str], bool] | None) -> None:
    """The owning Windows GUI session registers its bounded IPC sender."""
    if sink is not None and not callable(sink):
        raise TypeError("INVALID_REPAIR_SINK")
    global _gui_sink
    with _sink_lock:
        _gui_sink = sink


def clear_gui_repair_sink(sink=None) -> None:
    """A closing GUI must not disable a newer session's sender."""
    global _gui_sink
    with _sink_lock:
        if sink is None or _gui_sink == sink:
            _gui_sink = None


def gui_capture_active() -> bool:
    with _sink_lock:
        return _gui_sink is not None


def _pair_key_and_size(run_id, event_id, before, after):
    # Only fixed status codes reach a caller. Never put raw contents into an
    # exception, a filename, or a console message.
    if (type(run_id) is not str or not 1 <= len(run_id) <= 96
            or type(event_id) is not str or len(event_id) != 32):
        raise ValueError("INVALID_REPAIR_KEY")
    try:
        identity = UUID(hex=event_id)
    except ValueError:
        raise ValueError("INVALID_REPAIR_KEY") from None
    if identity.version != 4 or identity.hex != event_id:
        raise ValueError("INVALID_REPAIR_KEY")
    if (type(before) is not str or type(after) is not str
            or len(before) > MAX_TEXT_CHARS or len(after) > MAX_TEXT_CHARS):
        raise ValueError("REPAIR_PAIR_OVER_LIMIT")
    try:
        byte_size = len(before.encode("utf-8")) + len(after.encode("utf-8")) + 128
    except UnicodeError:
        raise ValueError("INVALID_REPAIR_ENCODING") from None
    if byte_size > MAX_PAIR_BYTES:
        raise ValueError("REPAIR_PAIR_OVER_LIMIT")
    return (run_id, event_id), byte_size


def publish_gui_repair(run_id: str, event_id: str, before: str, after: str) -> bool:
    """Best effort; a saturated/closed GUI must never stall an LLM Worker."""
    with _sink_lock:
        sink = _gui_sink
    if sink is None:
        return False
    try:
        _pair_key_and_size(run_id, event_id, before, after)
        return bool(sink(run_id, event_id, before, after))
    except Exception:
        return False


class RepairMemoryRing:
    """GUI-process-only bounded FIFO; snapshots are lost at process exit."""

    def __init__(self):
        self._items = OrderedDict()
        self._bytes = 0

    @property
    def count(self):
        return len(self._items)

    @property
    def total_bytes(self):
        return self._bytes

    def add(self, run_id, event_id, before, after) -> bool:
        try:
            key, size = _pair_key_and_size(run_id, event_id, before, after)
        except ValueError:
            return False
        # An event ID is a single immutable Quality receipt: reject replay,
        # do not overwrite legitimate evidence or promote duplicate to newest.
        if key in self._items:
            return False
        while self._items and (
            len(self._items) >= MAX_CASES or self._bytes + size > MAX_TOTAL_BYTES
        ):
            _, (_, _, removed_size) = self._items.popitem(last=False)
            self._bytes -= removed_size
        if size > MAX_TOTAL_BYTES:
            return False
        self._items[key] = (before, after, size)
        self._bytes += size
        return True

    def read(self, run_id, event_id):
        key, _ = _pair_key_and_size(run_id, event_id, "", "")
        try:
            before, after, _ = self._items[key]
        except KeyError:
            raise ValueError("MEMORY_REPAIR_NOT_AVAILABLE") from None
        return {"original": before, "repaired": after}

    def clear_run(self, run_id) -> int:
        if type(run_id) is not str or not 1 <= len(run_id) <= 96:
            return 0
        removed = 0
        for key in list(self._items):
            if key[0] == run_id:
                _, _, size = self._items.pop(key)
                self._bytes -= size
                removed += 1
        return removed

    def clear(self):
        self._items.clear()
        self._bytes = 0
