"""Run-scoped cooperative cancellation and bounded Reduction observability."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import threading
import time
import uuid
from types import MappingProxyType
from typing import Any, Mapping

from .execution import EventCancellationSignal, ExecutionCancelled, ExecutionContext
from .runtime_task import ProductionTaskRuntime

_MAX_LOG_BYTES = 30 * 1024 * 1024
_SAFE_SOURCES = frozenset({"gui", "external", "e2e"})
_SAFE_FIELDS = frozenset({
    "stage", "profile", "controller", "round_index", "input_index", "logical_id",
    "collection_id", "manifest_fingerprint", "aggregate_output_id", "attempted",
    "succeeded", "failed", "success_ratio", "partial_result", "stop_reason",
    "cancel_source", "error_type", "reason", "job_id",
})


def _owner(ctx: Any) -> Any:
    """Resolve non-mutating runtime overlays to their root run context."""
    seen: set[int] = set()
    current = ctx
    while id(current) not in seen:
        seen.add(id(current))
        base = getattr(current, "_base", None)
        if base is None:
            break
        current = base
    return current


def _state(ctx: Any) -> dict[str, Any]:
    ctx = _owner(ctx)
    state = getattr(ctx, "_reduction_production_control", None)
    if state is None:
        state = {"event": threading.Event(), "lock": threading.RLock(), "requested": False,
                 "source": "", "requested_at": ""}
        setattr(ctx, "_reduction_production_control", state)
    return state


def ensure_execution_cancel_event(ctx: Any) -> threading.Event:
    return _state(ctx)["event"]


def _safe_source(source: str) -> str:
    value = str(source or "").strip().lower()
    return value if value in _SAFE_SOURCES else "external"


def request_execution_cancel(ctx: Any, *, source: str) -> bool:
    """Request cancellation once. Return True only for the first request."""
    state = _state(ctx)
    with state["lock"]:
        if state["requested"]:
            return False
        state["requested"] = True
        state["source"] = _safe_source(source)
        state["requested_at"] = datetime.now(timezone.utc).isoformat()
        state["event"].set()
    observer = ensure_production_observer(ctx)
    observer.emit("cancellation_requested", {"cancel_source": state["source"]})
    return True


def execution_cancel_requested(ctx: Any) -> bool:
    return ensure_execution_cancel_event(ctx).is_set()


def production_cancellation_signal(ctx: Any) -> EventCancellationSignal:
    return EventCancellationSignal(ensure_execution_cancel_event(ctx))


def raise_if_execution_cancelled(ctx: Any) -> None:
    if execution_cancel_requested(ctx):
        raise ExecutionCancelled("execution cancelled")


def cancellation_metadata(ctx: Any) -> Mapping[str, Any]:
    state = _state(ctx)
    with state["lock"]:
        return MappingProxyType({k: state[k] for k in ("requested", "source", "requested_at")})


def _bounded(value: Any, limit: int = 160) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = "".join(ch for ch in str(value) if ch >= " " and ch != "\x7f")
    return text[:limit]


def _safe_job_id(ctx: Any) -> str:
    for name in ("config_path", "config_file", "pipeline_name"):
        value = getattr(ctx, name, None)
        if isinstance(value, str) and value.strip():
            return _bounded(Path(value).name, 96)
    return ""


@dataclass
class ProductionExecutionObserver:
    ctx: Any

    def __post_init__(self) -> None:
        self._lock = threading.RLock()
        self._stats = {key: 0 for key in (
            "stages_started", "stages_completed", "stages_failed", "stages_cancelled",
            "members_attempted", "members_succeeded", "members_failed",
            "partial_accepted", "partial_rejected", "cancellation_requested",
        )}
        self._stats["run_status"] = "running"
        self._run_id = _bounded(
            getattr(self.ctx, "reduction_run_id", "") or uuid.uuid4().hex, 96
        )
        self._gui_event_count = 0
        self._last_gui_publish = 0.0

    @property
    def path(self) -> Path:
        override = getattr(self.ctx, "reduction_execution_log_path", None)
        return Path(override) if override else Path(getattr(self.ctx, "PGMSubDir", ".")) / "logs" / "reduction_execution_events.jsonl"

    def _trim(self, path: Path) -> None:
        limit = int(getattr(self.ctx, "reduction_execution_log_max_bytes", _MAX_LOG_BYTES) or _MAX_LOG_BYTES)
        if path.exists() and path.stat().st_size > limit:
            with path.open("rb") as src:
                src.seek(max(0, path.stat().st_size - limit // 2))
                tail = src.read()
            newline = tail.find(b"\n")
            path.write_bytes(tail[newline + 1:] if newline >= 0 else b"")

    def emit(self, event: str, fields: Mapping[str, Any]) -> None:
        if not isinstance(event, str) or not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", event):
            return
        safe = {key: _bounded(value, 64 if "fingerprint" in key else 160)
                for key, value in fields.items() if key in _SAFE_FIELDS}
        for key in ("manifest_fingerprint", "aggregate_output_id"):
            if key in safe and isinstance(safe[key], str):
                safe[key] = safe[key][:16]
        record = {"schema_version": 1, "ts": datetime.now(timezone.utc).isoformat(),
                  "timezone": "UTC", "event": event, "run_id": self._run_id,
                  "mode": _bounded(getattr(self.ctx, "mode", ""), 32),
                  "job_id": _safe_job_id(self.ctx), **safe}
        with self._lock:
            updates = {
                "reduction_stage_started": "stages_started", "reduction_stage_completed": "stages_completed",
                "reduction_stage_failed": "stages_failed", "reduction_stage_cancelled": "stages_cancelled",
                "reduction_member_failed": "members_failed", "reduction_partial_accepted": "partial_accepted",
                "reduction_partial_rejected": "partial_rejected", "cancellation_requested": "cancellation_requested",
                "reduction_member_attempted": "members_attempted",
                "reduction_member_succeeded": "members_succeeded",
            }
            if event in updates:
                self._stats[updates[event]] += 1
            if event == "run_cancelled": self._stats["run_status"] = "cancelled"
            elif event == "run_completed" and self._stats["run_status"] == "running": self._stats["run_status"] = "completed"
            elif event == "run_failed": self._stats["run_status"] = "failed"
            counter_only = event in {"reduction_member_attempted", "reduction_member_succeeded"}
            if not counter_only:
                path = self.path
                path.parent.mkdir(parents=True, exist_ok=True)
                self._trim(path)
                with path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            self._gui_event_count += 1
            force = event in {
                "cancellation_requested", "reduction_partial_rejected",
                "reduction_stage_failed", "run_completed", "run_cancelled", "run_failed",
            }
        self.publish_snapshot(force=force)

    def snapshot(self) -> Mapping[str, Any]:
        with self._lock:
            return MappingProxyType(dict(self._stats))

    def publish_snapshot(self, *, force: bool = False) -> bool:
        """Throttled cumulative IPC snapshot; terminal/diagnostic states force delivery."""
        gui = getattr(self.ctx, "gui_handle", None)
        if gui is None or not callable(getattr(gui, "update_reduction_stats", None)):
            return False
        now = time.monotonic()
        with self._lock:
            if not force and self._gui_event_count < 20 and now - self._last_gui_publish < 0.25:
                return False
            snapshot = dict(self._stats)
            self._gui_event_count = 0
            self._last_gui_publish = now
        try:
            gui.update_reduction_stats(
                snapshot, final=force and snapshot["run_status"] != "running"
            )
            return True
        except Exception:
            return False


def ensure_production_observer(ctx: Any) -> ProductionExecutionObserver:
    ctx = _owner(ctx)
    observer = getattr(ctx, "_reduction_execution_observer", None)
    if observer is None:
        observer = ProductionExecutionObserver(ctx)
        setattr(ctx, "_reduction_execution_observer", observer)
    return observer


def build_production_execution_context(ctx: Any, *, reducer_context: Mapping[str, Any] | None = None,
                                       observability_tags: Mapping[str, Any] | None = None) -> ExecutionContext:
    tags = {
        key: _bounded(value, 96 if key in {"collection_id", "logical_id"} else 64)
        for key, value in dict(observability_tags or {}).items()
        if key in {"collection_id", "manifest_fingerprint", "aggregate_output_id"}
        and isinstance(value, (str, int, float, bool))
    }
    return ExecutionContext(runtime_ctx=ctx, task_runtime=ProductionTaskRuntime(ctx),
                            executable_registry=getattr(ctx, "executable_registry", None),
                            reducer_context=reducer_context or {},
                            cancellation=production_cancellation_signal(ctx),
                            observer=ensure_production_observer(ctx),
                            observability_tags=tags)
