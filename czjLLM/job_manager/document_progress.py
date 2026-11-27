"""Bounded per-document UI projection of the existing run Load Meter.

Read-only; does NOT infer SQL/ES acknowledgements from 100% LLM slices.
The GUI receives this snapshot via a background thread only when expanded.
"""
from __future__ import annotations

import time
import math
import os
import json
from pathlib import Path
import stat

MAX_METER_BYTES = 12 * 1024 * 1024
PAGE_SIZE = 12
MAX_ID_LENGTH = 85
_VISIBLE_STATES = {
    "merged": "Row Merger 已標 merged", "writeback_failed_schema": "寫回結構異常",
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


def _timestamp(value):
    """Validate Unix epoch seconds independently from slice-count limits.

    Real last_state_at is time.time() (~1.8 billion in 2026), so reusing
    _nonnegative() (max 1e9) silently discards all valid timestamps.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        timestamp = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    if not 946684800 <= timestamp <= 4102444800:
        return None
    return timestamp


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
        state in {"in_progress", "scheduling_multistage",
                  "ready_for_writeback", "ready_to_merge"}
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
    updated = _timestamp(row.get("last_state_at"))
    if updated is None:
        updated_text = "—"
    else:
        try:
            updated_text = time.strftime("%H:%M:%S", time.localtime(updated))
        except (ValueError, OverflowError, OSError):
            updated_text = "—"
    document_name = row.get("temp_txt")
    if isinstance(document_name, str) and document_name:
        # Only a local GUI basename, never the full source path or payload.
        name = document_name.replace("\\", "/").rsplit("/", 1)[-1]
        name = _safe_label(name)
        label = _safe_label(str(key) + " · " + name) if name else _safe_label(key)
    else:
        label = _safe_label(key)
    return {
        "key": str(key),
        "label": label,
        "state": state, "stage": status_text,
        "progress": progress,
        "done": done, "total": total,
        "pending": pending, "running": running,
        "pending_text": "—" if pending is None else str(pending),
        "running_text": "—" if running is None else str(running),
        "error": error, "active": active,
        "updated_at": updated,
        "updated_text": updated_text,
        "model_endpoint": "—",
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


def read_meter_strict(meter_path):
    """Read real run-meter evidence or raise. Never synthesize an empty run.

    Both the per-document panel and incident review must share this fail-
    closed reader. File-not-found may be handled explicitly by callers,
    while corruption, truncation and read errors must propagate.
    """
    path = Path(meter_path)
    if any(node.is_symlink() for node in (path, *path.parents)):
        raise ValueError("unsafe meter path")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_METER_BYTES:
        raise ValueError("meter file unsafe or exceeds read budget")
    # meter_read() falls back to an EMPTY DEFAULT after exhausted JSON
    # retries. That is appropriate for some coordinator paths but unsafe for
    # monitoring: a corrupt/unreadable live meter must never look like 0 jobs.
    # This reader retries a bounded number of times and raises on failure,
    # allowing the GUI to retain the last valid snapshot with an error notice.
    data = None
    last_error = None
    for attempt in range(5):
        try:
            if any(node.is_symlink() for node in (path, *path.parents)):
                raise ValueError("unsafe meter path")
            fd = os.open(
                path, os.O_RDONLY | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            with os.fdopen(fd, "rb") as fp:
                info = os.fstat(fp.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_METER_BYTES:
                    raise ValueError("meter file unsafe or exceeds read budget")
                payload = fp.read(MAX_METER_BYTES + 1)
            if len(payload) > MAX_METER_BYTES:
                raise ValueError("meter file unsafe or exceeds read budget")
            data = json.loads(payload)
            if not isinstance(data, dict) or not isinstance(data.get("rows"), dict):
                raise ValueError("invalid meter structure")
            break
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt != 4:
                time.sleep(0.05)
    if data is None:
        raise ValueError("meter unavailable after bounded retries") from last_error
    return data


def capture_activity_clock(observation, *, wall_ns, monotonic_s):
    """Anchor validated, same-host last-observed evidence to GUI monotonic time."""
    if observation.get("status") != "calling":
        return None
    observed_ns = observation.get("observed_ns")
    if type(observed_ns) is not int or not 0 < observed_ns <= wall_ns:
        return None
    age = (wall_ns - observed_ns) / 1e9
    if age > 1e9 or not math.isfinite(monotonic_s):
        return None
    activity = observation.get("stream_activity")
    if activity is not None and activity["event"] not in ("started", "received"):
        return None  # stream terminal: do not extrapolate
    return {"age_s": age, "anchor_s": monotonic_s, "stream_activity": activity}


def format_activity_clock(clock, *, monotonic_s):
    """Local elapsed estimates only; never infer a provider or GPU phase."""
    if clock is None:
        return "目前沒有可計時的呼叫觀測"
    delta = monotonic_s - clock["anchor_s"]
    if not math.isfinite(delta) or not 0 <= delta <= 1e9:
        return "本機計時暫無法核對"
    age = clock["age_s"] + delta
    detail = clock["stream_activity"]
    if detail is None:
        return f"距呼叫狀態最後觀測 {int(age)}s｜GPU 狀態未知"
    elapsed = detail["elapsed_s"] + age
    last = detail["last_chunk_elapsed_s"]
    gap = "首段資料尚未觀測" if last is None else (
        f"距最後資料約 {int(elapsed - last)}s"
    )
    return (f"串流開始後約 {int(elapsed)}s｜距最後觀測 {int(age)}s｜"
            f"{gap}｜GPU 狀態未知")


MAX_PAGE_ACTIVITY_CALLS = 24


def format_page_activity(snapshot, *, monotonic_s):
    """Format the bounded rendered-page projection without I/O."""
    if snapshot is None:
        return "目前頁呼叫觀測待重新核對"
    calls = snapshot.get("activity_calls", [])
    count = snapshot.get("activity_call_count", 0)
    if not calls:
        return "目前頁無可顯示的分派／呼叫觀測（不代表 GPU 閒置）"
    lines = [f"目前頁最後觀測 {count} 個呼叫｜顯示 {len(calls)} 個；非全 Run 或 GPU 使用率"]
    for call in calls:
        status = "已分派" if call["status"] == "assigned" else "呼叫中"
        detail = call.get("stream_activity")
        if detail is not None:
            status += (f"｜{detail['chunks']} chunks｜思考"
                       f"{'有' if detail['thinking_seen'] else '未觀測'}／回答"
                       f"{'有' if detail['content_seen'] else '未觀測'}")
            if detail["event"] in ("assembled", "failed"):
                status += "｜串流已組裝" if detail["event"] == "assembled" else "｜串流失敗"
        lines.append(f"{call['row_label']}｜{call['model']} · "
                     f"{call['endpoint_ip'] or 'IP 未記錄'}｜{status}（最後觀測）")
        if call.get("clock") is not None:
            lines.append("    " + format_activity_clock(call["clock"], monotonic_s=monotonic_s))
    if count > len(calls):
        lines.append(f"另有 {count-len(calls)} 個呼叫未顯示（頁面顯示上限）")
    return "\n".join(lines)


def read_document_progress(meter_path, *, mode="目前處理", search="",
                           page=0, page_size=PAGE_SIZE, audit_path=""):
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
    data = read_meter_strict(path)
    result = project_meter(data, mode=mode, search=search, page=page,
                           page_size=page_size)
    result["notice"] = "本次 Run；切片100%≠確認寫回"
    if audit_path and result["shown"]:
        # Only the visible page is joined; no source directories, LLM work,
        # configuration fallbacks or raw audit fields go into the GUI table.
        from czjLLM.job_manager.document_model_endpoint import (
            summarize_model_endpoint_pairs,
        )
        from czjLLM.job_manager.document_model_endpoint_incremental import (
            read_incremental_model_endpoints,
        )
        row_map = data["rows"]
        item_dirs = {
            item["key"]: row_map[item["key"]].get("item_dir")
            for item in result["shown"]
            if isinstance(row_map.get(item["key"]), dict)
        }
        try:
            observation = read_incremental_model_endpoints(audit_path, item_dirs)
        except (ValueError, OSError, UnicodeError):
            # Meter stays usable if CSV changed generation or has malformed
            # records. Do not display stale endpoints from earlier scans.
            result["notice"] += "；模型／端點 IP 的 Audit 暫無法核對"
        else:
            if observation["complete"]:
                for item in result["shown"]:
                    item["model_endpoint"] = summarize_model_endpoint_pairs(
                        observation["models"].get(item["key"], {})
                    )
            else:
                # A partial catch-up is NOT the latest endpoint. The next
                # scheduled UI refresh resumes from the verified byte cursor.
                result["notice"] += (
                    "；模型／端點 IP 的 Audit 增量讀取中"
                    f"（{observation['scanned_bytes']:,}/"
                    f"{observation['total_bytes']:,} bytes）"
                )
        # The selected Worker records the chosen model/IP *before* entering
        # CallLLMAPI, unlike the post-call audit. Its lifecycle evidence is a
        # separate, non-authoritative projection (not a provider HTTP receipt).
        from czjLLM.job_manager.worker_dispatch_observation import (
            read_visible_dispatch_observations,
        )
        try:
            dispatched = read_visible_dispatch_observations(audit_path, item_dirs)
        except (OSError, ValueError, UnicodeError):
            result["notice"] += "；Worker 分派狀態暫無法核對"
        else:
            result["activity_calls"] = []
            result["activity_call_count"] = 0
            wall_ns, monotonic_s = time.time_ns(), time.monotonic()
            for item in result["shown"]:
                latest = dispatched.get(item["key"], {})
                if latest.get("text"):
                    item["model_endpoint"] = latest["text"]
                    if item["state"] == "in_progress" and (item["running"] or 0) > 0:
                        clock = capture_activity_clock(latest, wall_ns=time.time_ns(),
                                                       monotonic_s=time.monotonic())
                        if clock is not None:
                            item["activity_clock"] = clock
                if item["state"] == "in_progress" and (item["running"] or 0) > 0:
                    result["activity_call_count"] += latest.get("active_count", 0)
                    for call in latest.get("active_calls", []):
                        if len(result["activity_calls"]) >= MAX_PAGE_ACTIVITY_CALLS:
                            break
                        result["activity_calls"].append({**call, "row_label": item["label"],
                            "clock": capture_activity_clock(call, wall_ns=wall_ns,
                                                            monotonic_s=monotonic_s)})
    return result
