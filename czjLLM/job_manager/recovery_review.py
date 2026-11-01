"""Durable operator review actions for recovery incidents.

Separation of duties:
  - queue_recovery_status.json is authoritative safety evidence.
  - queue_review_actions.jsonl only records operator UI decisions.
  - "delete" is a review-log tombstone, NEVER unlink of queue data or
    an authorization to clear a blocked state.

No prompt contents, filenames, paths, PKs or secrets are written to the
actions ledger; the GUI obtains item directories from the current run meter.
"""
from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path

from czjLLM.prompt_pipeline.runtime_support.prompt_queue import (
    QueueClaimRollbackError, read_recovery_status, recovery_status_path,
)

ACTIONS = frozenset(("resolved", "ignored", "deleted", "open"))
LOG_NAME = "queue_review_actions.jsonl"
MAX_LOG_BYTES = 1_048_576
MAX_ITEMS = 500
ISSUE_STATUSES = frozenset((
    "blocked_recovery", "writeback_failed_schema", "writeback_failed",
    "recovery_incomplete",
))
# The ledger is an operator acknowledgement history, not a queue lifecycle.
# It is safe to remove only its UI visibility, never work evidence.


def _review_log_path(item_dir):
    marker = recovery_status_path(item_dir)
    return marker.with_name(LOG_NAME)


def _safe_log_parent(item_dir):
    path = _review_log_path(item_dir)
    # Reject aliases in all ancestors, not only the final leaf.
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise QueueClaimRollbackError("unsafe review ledger path")
    if not path.parent.is_dir():
        if not Path(item_dir).is_dir():
            raise QueueClaimRollbackError("missing review item directory")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise QueueClaimRollbackError("unable to create review metadata directory") from exc
    if path.exists() and not stat.S_ISREG(path.lstat().st_mode):
        raise QueueClaimRollbackError("nonregular review ledger")
    return path


def _read_action_history(item_dir):
    path = _review_log_path(item_dir)
    if not path.exists():
        return []
    path = _safe_log_parent(item_dir)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(
        os, "O_NONBLOCK", 0
    ) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_LOG_BYTES:
            raise QueueClaimRollbackError("unsafe or oversized review ledger")
        raw = file.read(MAX_LOG_BYTES + 1)
    if len(raw) > MAX_LOG_BYTES:
        raise QueueClaimRollbackError("oversized review ledger")
    events = []
    for line in raw.splitlines():
        if not line:
            continue
        try:
            event = json.loads(line)
        except (ValueError, TypeError) as exc:
            raise QueueClaimRollbackError("invalid review audit record") from exc
        if (not isinstance(event, dict)
                or event.get("version") != 1
                or event.get("action") not in ACTIONS
                or not isinstance(event.get("ts"), (int, float))):
            raise QueueClaimRollbackError("invalid review audit record")
        events.append(event)
    return events


def _marker_summary(item_dir):
    marker_path = recovery_status_path(item_dir)
    # read_recovery_status distinguishes active blocked from recovered/pending;
    # recovered marker is NOT job success.
    active = read_recovery_status(item_dir)
    if active is not None:
        return active["code"], "blocked", active.get("recheck_count", 0)
    if marker_path.exists():
        # Reader accepted the marker as verified recovered/pending.
        return "VERIFIED_EXISTING_TODO", "pending", 0
    return None, "absent", 0


def review_snapshot(item_dir, *, row_status=None):
    """Return privacy-minimal issue summary, or None for no issue."""
    code, operational, count = _marker_summary(item_dir)
    history = _read_action_history(item_dir)
    if code is None and row_status not in ISSUE_STATUSES and not history:
        return None
    if code is None and history:
        code = history[-1]["code"]
    # Active Queue blocks outrank inactive markers. A current writeback
    # failure outranks a recovered/pending marker and stays visible.
    if operational != "blocked" and row_status in {
        "writeback_failed_schema", "writeback_failed",
    }:
        code = row_status
        operational = "writeback_failure"
    elif operational != "blocked" and row_status in {
        "blocked_recovery", "recovery_incomplete",
    }:
        code = row_status
        operational = "unknown"
    action = history[-1]["action"] if history else "open"
    if operational in ("blocked", "unknown", "writeback_failure") and action == "resolved":
        # Operator review is NOT authorization to clear a safety hold.
        action = "open"
    return {
        "code": code or str(row_status),
        "operational": operational,
        "review_state": action,
        "recheck_count": count,
        "actions_count": len(history),
        "needs_attention": operational in {
            "blocked", "unknown", "writeback_failure",
        } or action == "open",
    }


def list_review_items(meter_path=None, extra_item_dirs=()):
    """Current-run only; do not walk the entire disk looking for incidents."""
    item_map = {}
    if meter_path:
        from czjLLM.prompt_pipeline.runtime_support.load_meter import meter_read
        try:
            meter = meter_read(str(meter_path))
        except (OSError, ValueError, TypeError, KeyError):
            # The run meter may be rotated/removed after shutdown. An
            # explicitly chosen historic item directory must remain reviewable.
            if not extra_item_dirs:
                raise
            meter = {}
        rows = meter.get("rows", {})
        if isinstance(rows, dict):
            for row in rows.values():
                if not isinstance(row, dict):
                    continue
                path = row.get("item_dir")
                if isinstance(path, str) and path:
                    item_map[path] = str(row.get("status", ""))
    for path in extra_item_dirs:
        if isinstance(path, (str, Path)) and str(path):
            item_map.setdefault(str(path), None)
    if len(item_map) > MAX_ITEMS:
        raise ValueError("review item limit exceeded")
    results = []
    for path, status in item_map.items():
        try:
            summary = review_snapshot(path, row_status=status)
        except (QueueClaimRollbackError, OSError, ValueError):
            summary = {
                "code": "REVIEW_EVIDENCE_UNREADABLE",
                "operational": "unknown",
                "review_state": "open",
                "recheck_count": 0,
                "actions_count": 0,
                "needs_attention": True,
            }
        if summary is not None:
            results.append({
                "item_dir": str(path), "source_row_status": status,
                **summary,
            })
    return results


def set_review_action(item_dir, action, *, row_status=None):
    """Append operator decision to audit; NEVER mutate recovery marker."""
    if action not in ACTIONS:
        raise ValueError("unsupported review action")
    code, operational, _ = _marker_summary(item_dir)
    if code is None:
        previous = _read_action_history(item_dir)
        code = (str(row_status) if row_status in ISSUE_STATUSES
                else previous[-1]["code"] if previous else None)
    if code is None:
        raise QueueClaimRollbackError("review source must exist")
    # A currently failing writeback row is not resolved merely because it
    # lacks a queue-recovery marker.
    if action == "resolved" and row_status in ISSUE_STATUSES:
        raise QueueClaimRollbackError("cannot resolve active writeback failure")
    if action == "resolved" and operational == "blocked":
        raise QueueClaimRollbackError(
            "cannot mark unresolved blocked queue as resolved"
        )
    path = _safe_log_parent(item_dir)
    old = _read_action_history(item_dir)
    if len(old) >= 5000:
        raise QueueClaimRollbackError("review audit capacity exceeded")
    event = {
        "version": 1, "ts": time.time(), "action": action,
        "operational_at_review": operational,
        "code": code,
        "queue_modified": False,
    }
    encoded = (json.dumps(event, ensure_ascii=True, sort_keys=True) + "\n").encode(
        "ascii"
    )
    if path.exists() and path.stat().st_size + len(encoded) > MAX_LOG_BYTES:
        raise QueueClaimRollbackError("review audit capacity exceeded")
    flags = (os.O_WRONLY | os.O_APPEND | os.O_CREAT
             | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "ab") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise QueueClaimRollbackError("unsafe review audit destination")
        written = stream.write(encoded)
        if written != len(encoded):
            raise QueueClaimRollbackError("incomplete review audit write")
        stream.flush()
        os.fsync(stream.fileno())
    return event


# Clipboard exports use finite, explicitly whitelisted metadata only.
# Never copy full meter rows, filesystem paths, tracebacks or prompt data.
_DEBUG_CODES = frozenset((
    "TODO_CONFLICT", "UNSAFE_QUEUE_ENTRY", "RECOVERY_RETRIES_EXHAUSTED",
    "RECOVERY_SCAN_INCOMPLETE", "VERIFIED_EXISTING_TODO",
    "REVIEW_EVIDENCE_UNREADABLE", "blocked_recovery",
    "writeback_failed_schema", "writeback_failed", "recovery_incomplete",
))
_DEBUG_RUNTIME_STATES = frozenset((
    "blocked", "pending", "absent", "unknown", "writeback_failure",
))
MAX_DEBUG_ITEMS = 100


def format_incident_debug_report(incidents):
    """Pure safe copy/paste report; not a queue mutation or network upload."""
    incidents = list(incidents)
    if not 1 <= len(incidents) <= MAX_DEBUG_ITEMS:
        raise ValueError("debug report requires 1..100 incidents")

    def safe_enum(value, known):
        return value if isinstance(value, str) and value in known else "UNKNOWN"

    def safe_count(value):
        return value if type(value) is int and 0 <= value <= 100000 else "unknown"

    lines = [
        "# GenerativeLanguageModel 重大事件診斷摘要",
        "內容範圍：檢閱視窗選取的結構化異常（不是完整執行日誌）",
        "用途：協助 ChatGPT 分析可能原因與安全排查；不代表已確定根因。",
        "資料保護：不包含路徑、檔名、列 ID、Prompt、LLM 回應、金鑰或連線資訊。",
        "安全提醒：檢閱「已解決」不是 LLM/SQL/ES 寫回完成；"
        "「忽略／刪除檢閱紀錄」不會解除隔離。",
        f"條目數：{len(incidents)}", "",
    ]
    for idx, entry in enumerate(incidents, 1):
        if not isinstance(entry, dict):
            entry = {}
        lines.extend([
            f"## 異常 #{idx}",
            f"錯誤代碼：{safe_enum(entry.get('code'), _DEBUG_CODES)}",
            f"執行狀態：{safe_enum(entry.get('operational'), _DEBUG_RUNTIME_STATES)}",
            f"檢閱狀態：{safe_enum(entry.get('review_state'), ACTIONS)}",
            f"來源列狀態：{safe_enum(entry.get('source_row_status'), ISSUE_STATUSES)}",
            f"安全復查次數：{safe_count(entry.get('recheck_count'))}",
            f"檢閱操作次數：{safe_count(entry.get('actions_count'))}",
            "需注意：是" if entry.get("needs_attention") is True else "需注意：否/未知",
            "",
        ])
    lines.append(
        "請分析可能原因、哪些額外去識別化證據有助定位，以及不刪除 Success、"
        "不覆寫 TODO/RUNNING、不重複 SQL/ES 寫回的安全修復方法。"
    )
    return "\n".join(lines) + "\n"
