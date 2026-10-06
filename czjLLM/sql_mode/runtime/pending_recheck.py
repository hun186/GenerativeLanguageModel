# sql_mode/runtime/pending_recheck.py
from __future__ import annotations

import json
import os
import threading
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

from czjLLM.job_manager.console_ui import tlog, tlog_warn

PENDING_SKIP_LOG_MAX_BYTES = 30 * 1024 * 1024
PENDING_EVENT_LOG_MAX_BYTES = 30 * 1024 * 1024
JOB_IDENTIFIER_MAX_CHARS = 160
SEMANTIC_STALE_REASONS = {
    "missing_processing_identity", "execution_fingerprint_mismatch",
    "stale_by_policy", "model_tag_mismatch", "pipeline_hash_mismatch",
    "stale_after_days", "force_since", "required_output_invalid", "missing_meta",
}
_RECHECK_LOCK_INIT = threading.Lock()


def _recheck_stats_lock(ctx):
    lock = getattr(ctx, "_pending_recheck_stats_lock", None)
    if lock is not None:
        return lock
    with _RECHECK_LOCK_INIT:
        lock = getattr(ctx, "_pending_recheck_stats_lock", None)
        if lock is None:
            lock = threading.RLock()
            setattr(ctx, "_pending_recheck_stats_lock", lock)
    return lock


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


def pending_event_log_path(ctx) -> Path:
    configured = getattr(ctx, "pending_recheck_event_log_path", None)
    if configured:
        return Path(configured)
    return Path(getattr(ctx, "PGMSubDir", ".") or ".") / "logs" / "pending_recheck_events.jsonl"


def pending_event_log_max_bytes(ctx) -> int:
    try:
        return max(int(getattr(ctx, "pending_recheck_event_log_max_bytes", PENDING_EVENT_LOG_MAX_BYTES)), 1024)
    except (TypeError, ValueError):
        return PENDING_EVENT_LOG_MAX_BYTES


def _fingerprint_prefix(value: Any) -> str | None:
    return str(value)[:12] if value else None


def record_pending_event(ctx, pk: Any, decision, *, phase: str = "dispatch") -> None:
    """Append one bounded, payload-free canonical diagnostic event."""
    path = pending_event_log_path(ctx)
    max_bytes = pending_event_log_max_bytes(ctx)
    path.parent.mkdir(parents=True, exist_ok=True)
    trim_log_to_half_if_needed(path, max_bytes)
    now = datetime.now().astimezone()
    diagnostics = dict(getattr(decision, "diagnostics", {}) or {})
    record = {
        "ts": now.isoformat(), "timezone": now.tzname(), "phase": phase,
        "mode": "es" if "elasticsearch" in getattr(getattr(ctx, "_pending_adapter", None), "__class__", type(None)).__name__.lower() else "sql",
        "task_json": task_json_name(ctx),
        "target": getattr(ctx, "_pending_tgt_table", getattr(ctx, "target_table", None)),
        "pk": str(pk),
        "adapter": getattr(getattr(ctx, "_pending_adapter", None), "__class__", type(None)).__name__,
        "decision": "process" if decision.pending else "skip", "reason": decision.reason,
        "output_cols": getattr(ctx, "output_cols", None) or [getattr(ctx, "output_col", "")],
    }
    for key in ("expected_execution_fingerprint", "persisted_execution_fingerprint"):
        if diagnostics.get(key):
            record[key] = _fingerprint_prefix(diagnostics[key])
    secondary = diagnostics.get("secondary_reasons")
    if secondary:
        record["secondary_reasons"] = list(secondary)[:8]
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(record, ensure_ascii=False) + "\n")
    trim_log_to_half_if_needed(path, max_bytes)


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
    path_attrs = (
        "task_json_name",
        "task_json",
        "json_config_file",
        "sql_config_file",
        "es_config_file",
        "config_file",
        "config_path",
    )
    for attr in path_attrs:
        value = getattr(ctx, attr, None)
        if not isinstance(value, (str, os.PathLike)):
            continue
        raw = os.fspath(value)
        if not isinstance(raw, str):
            continue
        normalized = "".join(
            ch for ch in raw if not unicodedata.category(ch).startswith("C")
        ).strip()
        if normalized:
            return Path(normalized.replace("\\", "/")).name[:JOB_IDENTIFIER_MAX_CHARS] or "unknown"
    pipeline_name = getattr(ctx, "pipeline_name", None)
    if isinstance(pipeline_name, str):
        normalized = "".join(
            ch for ch in pipeline_name
            if not unicodedata.category(ch).startswith("C") and ch not in "/\\"
        ).strip()
        if normalized:
            return normalized[:JOB_IDENTIFIER_MAX_CHARS]
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


def _stats_attr(scope: str) -> str:
    return "_pending_recheck_stats" if scope == "dispatch" else f"_pending_recheck_{scope}_stats"


def _bump_recheck_stat(ctx, name: str, *, scope: str = "dispatch") -> int:
    with _recheck_stats_lock(ctx):
        attr = _stats_attr(scope)
        stats = getattr(ctx, attr, None)
        if not isinstance(stats, dict):
            stats = {"checked": 0, "pending": 0, "already_completed": 0, "errors": 0}
            try:
                setattr(ctx, attr, stats)
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


def pending_recheck_stats(ctx, *, scope: str = "dispatch") -> dict:
    with _recheck_stats_lock(ctx):
        stats = getattr(ctx, _stats_attr(scope), None)
        if not isinstance(stats, dict):
            stats = {}
        reasons = dict(stats.get("reasons", {}) or {})
        result = {
            "checked": int(stats.get("checked", 0) or 0),
            "pending": int(stats.get("pending", 0) or 0),
            "already_completed": int(stats.get("already_completed", 0) or 0),
            "errors": int(stats.get("errors", 0) or 0),
            "reasons": reasons,
        }
        checked = result["checked"]
        result["skip_rate"] = result["already_completed"] / checked if checked else 0.0
        result["recheck_error_rate"] = result["errors"] / checked if checked else 0.0
        result["semantic_stale_count"] = sum(
            int(reasons.get(k, 0) or 0) for k in SEMANTIC_STALE_REASONS
        )
        return result


def _bump_reason(ctx, reason: str, *, scope: str) -> None:
    with _recheck_stats_lock(ctx):
        attr = _stats_attr(scope)
        stats = getattr(ctx, attr, None)
        if not isinstance(stats, dict):
            _bump_recheck_stat(ctx, "checked", scope=scope)
            stats = getattr(ctx, attr)
            stats["checked"] -= 1
        reasons = stats.setdefault("reasons", {})
        reasons[reason] = int(reasons.get(reason, 0) or 0) + 1


def _push_gui_stats(ctx, *, scope: str, final: bool = False) -> None:
    if scope != "dispatch":
        return
    gui = getattr(ctx, "gui_handle", None)
    if gui is None or not callable(getattr(gui, "update_recheck_stats", None)):
        return
    with _recheck_stats_lock(ctx):
        stats = pending_recheck_stats(ctx, scope=scope)
        every = max(int(getattr(ctx, "pending_recheck_gui_every", 100) or 100), 1)
        try:
            max_seconds = max(
                float(getattr(ctx, "pending_recheck_gui_seconds", 1.0) or 1.0), 0.1
            )
        except (TypeError, ValueError):
            max_seconds = 1.0
        now = time.monotonic()
        try:
            last = float(
                getattr(ctx, "_pending_recheck_gui_last_push_monotonic", 0.0) or 0.0
            )
        except (TypeError, ValueError):
            last = 0.0
        checked = stats["checked"]
        count_due = checked <= 1 or checked % every == 0
        time_due = last <= 0.0 or now - last >= max_seconds
        if final or count_due or time_due:
            # Queue submission and timestamp update stay inside the same run-scoped
            # lock, so parallel producer workers cannot enqueue an older snapshot
            # after a newer one or independently defeat the throttle.
            gui.update_recheck_stats(stats)
            try:
                setattr(ctx, "_pending_recheck_gui_last_push_monotonic", now)
            except Exception:
                pass


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


def still_pending_before_dispatch(
    ctx,
    pk: Any,
    *,
    stats_scope: str = "dispatch",
    log_state: bool = True,
) -> bool:
    """Recheck remote SQL/ES state immediately before slicing/dispatching a row."""
    if not announce_pending_recheck_if_enabled(ctx):
        return True

    adapter = getattr(ctx, "_pending_adapter")
    output_cols = getattr(ctx, "output_cols", None) or [getattr(ctx, "output_col", "")]
    try:
        checker = getattr(adapter, "check_row_pending", None)
        decision = checker(
            tgt_table=getattr(ctx, "_pending_tgt_table", getattr(ctx, "target_table", None)),
            pk=getattr(ctx, "primary_key", ""),
            pk_value=pk,
            output_cols=output_cols,
        ) if callable(checker) else None
        is_pending = bool(decision.pending) if decision is not None else bool(adapter.is_row_pending(
            tgt_table=getattr(ctx, "_pending_tgt_table", getattr(ctx, "target_table", None)), pk=getattr(ctx, "primary_key", ""), pk_value=pk, output_cols=output_cols))
        reason = decision.reason if decision is not None else ("missing_output" if is_pending else "fresh_completed")
        with _recheck_stats_lock(ctx):
            _bump_recheck_stat(ctx, "checked", scope=stats_scope)
            state = "pending" if is_pending else "already_completed"
            current_count = _bump_recheck_stat(ctx, state, scope=stats_scope)
            _bump_reason(ctx, reason, scope=stats_scope)
            _push_gui_stats(ctx, scope=stats_scope)
        important = (not is_pending) or reason not in {"missing_output", "row_missing"}
        if important or getattr(ctx, "debug_pending_recheck_events", False):
            if decision is None:
                from czjLLM.common.pending_decision import PendingDecision
                decision = PendingDecision(is_pending, reason)
            record_pending_event(ctx, pk, decision, phase=stats_scope)
        if log_state and (
            getattr(ctx, "debug_pending_recheck", False)
            or current_count <= _get_recheck_log_limit(ctx)
        ):
            phase = "" if stats_scope == "dispatch" else f" phase={stats_scope}"
            tlog(f"[producer] pending recheck{phase} pk={pk} state={state}")
        return is_pending
    except Exception as e:
        # Fail open for availability: if the remote completion state cannot be
        # confirmed, treat the row/doc as still pending instead of skipping it.
        # This may do duplicate work, but avoids losing a row because a best-effort
        # recheck failed.
        with _recheck_stats_lock(ctx):
            _bump_recheck_stat(ctx, "checked", scope=stats_scope)
            _bump_recheck_stat(ctx, "errors", scope=stats_scope)
            _bump_reason(ctx, "recheck_error_fail_open", scope=stats_scope)
            _push_gui_stats(ctx, scope=stats_scope)
        from czjLLM.common.pending_decision import PendingDecision
        record_pending_event(ctx, pk, PendingDecision(True, "recheck_error_fail_open"), phase=stats_scope)
        tlog_warn(
            f"[producer] pending recheck 失敗 pk={pk}: {e!r}；"
            "無法確認是否已完成，保守視為仍待處理並繼續排程。"
        )
        return True


def still_pending_for_running_finalize(ctx, pk: Any) -> bool:
    """Recheck completion only for pending-running console cleanup after scheduling.

    This does not save LLM compute; dispatch-time rechecks are counted separately.
    """
    return still_pending_before_dispatch(
        ctx,
        pk,
        stats_scope="finalize",
        log_state=bool(getattr(ctx, "debug_pending_recheck_finalize", False)),
    )


def recheck_scheduled_after_writeback(ctx) -> dict:
    """Verify scheduled rows after merger/writeback shutdown has completed."""
    scheduled_pks = getattr(ctx, "_pending_recheck_scheduled_pks", None)
    if not scheduled_pks:
        return pending_recheck_stats(ctx, scope="completion")

    # This is the authoritative completion check.  The earlier ``finalize``
    # check only releases pending-running coordination state and can race with
    # the last writeback even after the queue meter reaches zero.
    for pk in scheduled_pks:
        still_pending_before_dispatch(
            ctx,
            pk,
            stats_scope="completion",
            log_state=False,
        )
    return pending_recheck_stats(ctx, scope="completion")


def _format_pending_recheck_completion_summary(
    ctx,
    *,
    total_rows: int | None = None,
    scheduled_rows: int | None = None,
    done_rows: int | None = None,
) -> list[str]:
    dispatch = pending_recheck_stats(ctx)
    finalize = pending_recheck_stats(ctx, scope="finalize")
    completion = pending_recheck_stats(ctx, scope="completion")
    if dispatch["checked"] <= 0 and finalize["checked"] <= 0 and completion["checked"] <= 0:
        return []

    lines = ["📌 pending recheck 最終摘要："]
    if total_rows is not None:
        lines.append(f"  - 候選總列數：{int(total_rows)}")
    lines.append(
        "  - 派工前重查："
        f"checked={dispatch['checked']}, "
        f"需處理={dispatch['pending']}, "
        f"已完成跳過={dispatch['already_completed']}, "
        f"errors={dispatch['errors']}"
    )
    lines.append(
        f"  - fresh skip={dispatch['already_completed']} ({dispatch['skip_rate']:.1%}); "
        f"semantic stale={dispatch['semantic_stale_count']}; "
        f"recheck errors={dispatch['errors']} ({dispatch['recheck_error_rate']:.2%})"
    )
    if dispatch["reasons"]:
        lines.append("  - reasons: " + ", ".join(f"{k}={v}" for k, v in sorted(dispatch["reasons"].items())))
    if scheduled_rows is not None:
        lines.append(f"  - producer 實際送出列數：{int(scheduled_rows)}")
    if finalize["checked"] > 0:
        lines.append(
            "  - running 中控清理快照（可能早於最後寫回）："
            f"checked={finalize['checked']}, "
            f"仍未完成={finalize['pending']}, "
            f"已完成={finalize['already_completed']}, "
            f"errors={finalize['errors']}"
        )
    if completion["checked"] > 0:
        lines.append(
            "  - 寫回完成後最終重查："
            f"checked={completion['checked']}, "
            f"仍未完成={completion['pending']}, "
            f"已完成={completion['already_completed']}, "
            f"errors={completion['errors']}"
        )
    if done_rows is not None:
        lines.append(f"  - 完成進度列數：{int(done_rows)}")
    lines.append(
        "  - 說明：派工前 pending 代表當下仍需處理，不是佇列卡住；"
        "running 中控清理只是過程快照；是否完成請以寫回完成後最終重查為準。"
    )
    return lines


def emit_pending_recheck_completion_summary(
    ctx,
    *,
    total_rows: int | None = None,
    scheduled_rows: int | None = None,
    done_rows: int | None = None,
) -> None:
    _push_gui_stats(ctx, scope="dispatch", final=True)
    for line in _format_pending_recheck_completion_summary(
        ctx,
        total_rows=total_rows,
        scheduled_rows=scheduled_rows,
        done_rows=done_rows,
    ):
        tlog(line)
