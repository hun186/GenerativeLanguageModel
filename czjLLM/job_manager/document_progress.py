"""Bounded per-document UI projection of the existing run Load Meter.

Read-only; does NOT infer SQL/ES acknowledgements from 100% LLM slices.
The GUI receives this snapshot via a background thread only when expanded.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
import stat

MAX_METER_BYTES = 12 * 1024 * 1024
PAGE_SIZE = 12
MAX_ID_LENGTH = 85
_VISIBLE_STATES = {
    "merged": "已合併／寫回", "writeback_failed_schema": "寫回結構異常",
    "writeback_failed": "寫回失敗", "blocked_recovery": "復原隔離",
    "recovery_incomplete": "復原不完整", "cancelled": "已取消",
    "ready_to_merge": "待合併／寫回", "ready_for_writeback": "待寫回",
    "scheduling_multistage": "多階段處理中", "in_progress": "處理中",
    "pending": "等待中", "failed": "失敗",
}
_ERROR_STATES = frozenset({
    "writeback_failed_schema", "writeback_failed", "blocked_recovery",
    "recovery_incomplete", "failed",
})
_FINISHED_STATES = frozenset({"merged", "cancelled", "failed",
                            "writeback_failed_schema", "writeback_failed"})


def _nonnegative(value):
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if number < 0 or number > 10**9:
        return None
    return number


def _safe_label(value):
    label = str(value)
    # No multiline labels: do not allow text from a meter to change table layout.
    label = "".join(c if (c.isprintable() and c not in "\r\n\t") else "?" for c in label)
    return label[:MAX_ID_LENGTH] + ("…" if len(label) > MAX_ID_LENGTH else "")


def classify_row(key, row):
    """Return immutable presentation data without mutating meter or source."""
    if not isinstance(row, dict):
        row = {}
    total = _nonnegative(row.get("total"))
    done = _nonnegative(row.get("done"))
    pending = _nonnegative(row.get("queue_pending"))
    running = _nonnegative(row.get("queue_running"))
    raw = row.get("status")
    state = raw if isinstance(raw, str) and raw in _VISIBLE_STATES else "unknown"
    error = state in _ERROR_STATES
    finalized = state in _FINISHED_STATES
    active = (not finalized and (
        state in {"scheduling_multistage", "ready_for_writeback", "ready_to_merge"}
        or (running is not None and running > 0)
        or (pending is not None and pending > 0)
        or (done is not None and done > 0 and (total is None or done < total))
    ))
    # 100% means completed LLM slices, NEVER SQL/ES sink success.
    if total is not None and total > 0 and done is not None:
        fraction = min(1.0, done / total)
        pct = round(100 * fraction)
        blocks = min(10, max(0, int(fraction * 10)))
        progress = f"{'▰' * blocks}{'▱' * (10 - blocks)} {pct}% ({done}/{total})"
    else:
        progress = "—（切片總數未記錄）"
    if state == "in_progress":
        if (running or 0) > 0:
            status_text = "LLM 執行中"
        elif (pending or 0) > 0:
            status_text = "切片等待中"
        elif total is not None and done is not None and total > 0 and done >= total:
            status_text = "切片完成；待合併／寫回"
        else:
            status_text = "處理中／狀態未細分"
    else:
        status_text = _VISIBLE_STATES.get(state, "未記錄／未知狀態")
    return {
        "key": str(key),
        "label": _safe_label(key),
        "state": state, "stage": status_text,
        "progress": progress,
        "done": done, "total": total,
        "pending": pending, "running": running,
        "pending_text": "—" if pending is None else str(pending),
        "running_text": "—" if running is None else str(running),
        "error": error, "active": active,
        "updated_at": _nonnegative(row.get("last_state_at")),
    }


def _rank(row):
    if row["error"]:
        return 0
    if (row["running"] or 0) > 0:
        return 1
    if row["state"] == "scheduling_multistage":
        return 2
    if row["state"] in {"ready_to_merge", "ready_for_writeback"}:
        return 3
    if (row["pending"] or 0) > 0:
        return 4
    if row["active"]:
        return 5
    return 6


def _item_filter(item, mode, needle):
    if mode == "異常":
        qualifies = item["error"]
    elif mode == "目前處理":
        qualifies = item["active"] or item["error"]
    else:
        qualifies = True
    return qualifies and (not needle or needle.casefold() in item["key"].casefold())


def project_meter(meter, *, mode="目前處理", search="", page=0,
                  page_size=PAGE_SIZE):
    """Supports arbitrarily many rows with O(N) scan, O(page_size) rendering."""
    if mode not in {"目前處理", "異常", "全部"}:
        raise ValueError("unknown row filter")
    if not isinstance(meter, dict):
        raise ValueError("invalid meter snapshot")
    raw_rows = meter.get("rows", {})
    if not isinstance(raw_rows, dict):
        raise ValueError("invalid meter rows")
    if type(page) is not int or page < 0 or page_size not in range(1, 101):
        raise ValueError("invalid page")
    if not isinstance(search, str) or len(search) > 100:
        raise ValueError("invalid search string")
    all_rows = [classify_row(k, v) for k, v in raw_rows.items()]
    filtered = [x for x in all_rows if _item_filter(x, mode, search)]
    filtered.sort(key=lambda x: (_rank(x), x["key"]))
    total = len(filtered)
    page_count = max(1, (total + page_size - 1) // page_size)
    page = min(page, page_count - 1)
    shown = filtered[page * page_size: (page + 1) * page_size]
    return {
        "all": len(all_rows), "matching": total, "page": page,
        "pages": page_count, "page_size": page_size,
        "active": sum(bool(x["active"]) for x in all_rows),
        "errors": sum(bool(x["error"]) for x in all_rows),
        "shown": shown,
    }


def read_document_progress(meter_path, *, mode="目前處理", search="",
                           page=0, page_size=PAGE_SIZE):
    """Bounded read: no queue directory scan, no prompt content inspection."""
    if not meter_path:
        return {**project_meter({}, mode=mode, search=search, page=page,
                                page_size=page_size), "notice": "尚未收到本次 Run Meter"}
    path = Path(meter_path)
    if any(node.is_symlink() for node in (path, *path.parents)):
        raise ValueError("unsafe meter path")
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {**project_meter({}, mode=mode, search=search, page=page,
                                page_size=page_size), "notice": "Meter 尚未建立"}
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_METER_BYTES:
        raise ValueError("meter file unsafe or exceeds read budget")
    from czjLLM.prompt_pipeline.runtime_support.load_meter import meter_read
    data = meter_read(str(path))
    result = project_meter(data, mode=mode, search=search, page=page,
                           page_size=page_size)
    result["notice"] = "本次 Run；切片100%≠確認寫回"
    return result
