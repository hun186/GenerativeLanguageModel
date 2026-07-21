# sql_mode/runtime/pending_recheck.py
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from czjLLM.job_manager.console_ui import tlog, tlog_warn

PENDING_SKIP_LOG_MAX_BYTES = 30 * 1024 * 1024


def pending_skip_log_path(ctx) -> Path:
    configured = getattr(ctx, "pending_recheck_skip_log_path", None)
    if configured:
        return Path(configured)
    base_dir = Path(getattr(ctx, "PGMSubDir", ".") or ".")
    return base_dir / "logs" / "pending_recheck_skips.log"


def pending_skip_log_max_bytes(ctx) -> int:
    raw = getattr(ctx, "pending_recheck_skip_log_max_bytes", PENDING_SKIP_LOG_MAX_BYTES)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = PENDING_SKIP_LOG_MAX_BYTES
    return max(value, 1024)


def trim_log_to_half_if_needed(path: Path, max_bytes: int) -> None:
    if not path.exists() or path.stat().st_size <= max_bytes:
        return

    keep_bytes = max(max_bytes // 2, 1)
    with path.open("rb") as fp:
        fp.seek(0, os.SEEK_END)
        size = fp.tell()
        fp.seek(max(size - keep_bytes, 0), os.SEEK_SET)
        data = fp.read()

    first_newline = data.find(b"\n")
    if first_newline >= 0 and first_newline + 1 < len(data):
        data = data[first_newline + 1:]

    with path.open("wb") as fp:
        fp.write(data)


def task_json_name(ctx) -> str:
    for attr in (
        "task_json_name",
        "task_json",
        "json_config_file",
        "sql_config_file",
        "es_config_file",
        "config_file",
        "config_path",
        "task",
        "pipeline_name",
    ):
        value = getattr(ctx, attr, None)
        if value:
            return Path(str(value)).name
    return "unknown"


def record_pending_skip(ctx, pk: Any) -> None:
    path = pending_skip_log_path(ctx)
    max_bytes = pending_skip_log_max_bytes(ctx)
    path.parent.mkdir(parents=True, exist_ok=True)
    trim_log_to_half_if_needed(path, max_bytes)

    local_now = datetime.now().astimezone()
    record = {
        "ts": local_now.isoformat(),
        "timezone": local_now.tzname(),
        "pid": os.getpid(),
        "task_json": task_json_name(ctx),
        "pk": str(pk),
        "target": getattr(ctx, "_pending_tgt_table", getattr(ctx, "target_table", None)),
        "output_cols": getattr(ctx, "output_cols", None) or [getattr(ctx, "output_col", "")],
        "adapter": getattr(getattr(ctx, "_pending_adapter", None), "__class__", type(None)).__name__,
        "reason": "already_completed",
    }
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    trim_log_to_half_if_needed(path, max_bytes)


def _bump_recheck_stat(ctx, name: str) -> int:
    stats = getattr(ctx, "_pending_recheck_stats", None)
    if not isinstance(stats, dict):
        stats = {"checked": 0, "pending": 0, "already_completed": 0, "errors": 0}
        try:
            setattr(ctx, "_pending_recheck_stats", stats)
        except Exception:
            pass
    stats[name] = int(stats.get(name, 0) or 0) + 1
    return stats[name]


def _get_recheck_log_limit(ctx) -> int:
    raw = getattr(ctx, "pending_recheck_log_first", 10)
    try:
        return max(int(raw), 0)
    except (TypeError, ValueError):
        return 10


def pending_recheck_stats(ctx) -> dict:
    stats = getattr(ctx, "_pending_recheck_stats", None)
    if not isinstance(stats, dict):
        return {"checked": 0, "pending": 0, "already_completed": 0, "errors": 0}
    return {
        "checked": int(stats.get("checked", 0) or 0),
        "pending": int(stats.get("pending", 0) or 0),
        "already_completed": int(stats.get("already_completed", 0) or 0),
        "errors": int(stats.get("errors", 0) or 0),
    }


def announce_pending_recheck_if_enabled(ctx) -> bool:
    """Log once when a SQL/ES adapter can recheck pending state before dispatch."""
    adapter = getattr(ctx, "_pending_adapter", None)
    if adapter is None or not hasattr(adapter, "is_row_pending"):
        return False

    if not getattr(ctx, "_pending_recheck_announced", False):
        source_kind = adapter.__class__.__name__
        output_cols = getattr(ctx, "output_cols", None) or [getattr(ctx, "output_col", "")]
        target = getattr(ctx, "_pending_tgt_table", getattr(ctx, "target_table", None))
        tlog(
            "[producer] pending recheck 自動啟用：偵測到遠端 SQL/ES adapter，"
            "每列切片/派工前會再次確認目標列/doc 是否仍未完成；"
            f"若 pk 已完成會略過。adapter={source_kind}, target={target}, output_cols={output_cols}"
        )
        try:
            setattr(ctx, "_pending_recheck_announced", True)
        except Exception:
            pass
    return True


def still_pending_before_dispatch(ctx, pk: Any) -> bool:
    """Recheck remote SQL/ES state immediately before slicing/dispatching a row."""
    if not announce_pending_recheck_if_enabled(ctx):
        return True

    adapter = getattr(ctx, "_pending_adapter")
    output_cols = getattr(ctx, "output_cols", None) or [getattr(ctx, "output_col", "")]
    try:
        is_pending = bool(adapter.is_row_pending(
            tgt_table=getattr(ctx, "_pending_tgt_table", getattr(ctx, "target_table", None)),
            pk=getattr(ctx, "primary_key", ""),
            pk_value=pk,
            output_cols=output_cols,
        ))
        _bump_recheck_stat(ctx, "checked")
        state = "pending" if is_pending else "already_completed"
        current_count = _bump_recheck_stat(ctx, state)
        if getattr(ctx, "debug_pending_recheck", False) or current_count <= _get_recheck_log_limit(ctx):
            tlog(f"[producer] pending recheck pk={pk} state={state}")
        return is_pending
    except Exception as e:
        # Fail open for availability: if the remote completion state cannot be
        # confirmed, treat the row/doc as still pending instead of skipping it.
        # This may do duplicate work, but avoids losing a row because a best-effort
        # recheck failed.
        _bump_recheck_stat(ctx, "checked")
        _bump_recheck_stat(ctx, "errors")
        tlog_warn(
            f"[producer] pending recheck 失敗 pk={pk}: {e!r}；"
            "無法確認是否已完成，保守視為仍待處理並繼續排程。"
        )
        return True
