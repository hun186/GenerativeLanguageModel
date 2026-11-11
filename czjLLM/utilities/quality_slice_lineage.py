"""Path-context-only quality diagnostic hints for queued slice observations.

Only opaque, fixed-length SHA256 digests leave this function; never persist
the absolute work-item path, prompt contents, SQL/ES PKs or source documents.

This is not an authoritative document UUID: moving/renaming work items,
noncanonical filesystem aliases or replacing a file can change its lineage.
It is a best-effort stable locator for TODO <-> RUNNING <-> Success during
one unchanged work-item location. Historical basename-only events cannot
be reconstructed.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

_QUEUE_DIRS = frozenset({"TODO", "RUNNING", "Success"})


def quality_slice_location_hints(slice_id: str) -> tuple[str, str]:
    """Return (work_item_hint, slice_trace_hint); empty pair on unknown paths.

    Hash a normalized work-item directory + filename, never the queue-state
    directory (TODO vs RUNNING), so a claimed/retried same-named slice retains
    the trace. Different work-item roots with "1.txt" no longer alias.
    """
    if (not isinstance(slice_id, str) or not slice_id or
            len(slice_id) > 4096 or "\x00" in slice_id):
        return "", ""
    try:
        path = Path(slice_id)
        if (path.parent.name not in _QUEUE_DIRS or
                path.suffix.lower() != ".txt" or not path.stem):
            return "", ""
        root = os.path.normcase(os.path.normpath(os.path.abspath(
            str(path.parent.parent),
        )))
        filename = os.path.normcase(path.name)
        if not root or len(root) > 4096:
            return "", ""
        root_bytes = root.encode("utf-8", "surrogatepass")
        leaf_bytes = filename.encode("utf-8", "surrogatepass")
        work = hashlib.sha256(b"quality-work-item-v1\0" + root_bytes).hexdigest()[:24]
        trace = hashlib.sha256(
            b"quality-slice-v1\0" + root_bytes + b"\0" + leaf_bytes
        ).hexdigest()[:24]
        return work, trace
    except (OSError, ValueError, UnicodeError, TypeError):
        return "", ""
