from __future__ import annotations

import json
import os
import time
from datetime import datetime
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO, Iterable, Sequence

if os.name == "nt":
    import msvcrt
else:
    import fcntl



def tlog(message):
    print(message)


def tlog_warn(message):
    print(message)

DEFAULT_TTL_SECONDS = 24 * 60 * 60
ADJUST_LOG_MAX_BYTES = 30 * 1024 * 1024


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


def _enabled(ctx) -> bool:
    return bool(getattr(ctx, "pending_running_console_enabled", True))


def _console_path(ctx) -> Path:
    configured = getattr(ctx, "pending_running_console_path", None)
    if configured:
        return Path(configured)
    base_dir = Path(getattr(ctx, "PGMSubDir", ".") or ".")
    return base_dir / "logs" / "pending_running_console.json"


def _adjust_log_path(ctx) -> Path:
    configured = getattr(ctx, "pending_running_console_log_path", None)
    if configured:
        return Path(configured)
    base_dir = Path(getattr(ctx, "PGMSubDir", ".") or ".")
    return base_dir / "logs" / "pending_running_console_adjustments.log"


def _adjust_log_max_bytes(ctx) -> int:
    raw = getattr(ctx, "pending_running_console_log_max_bytes", ADJUST_LOG_MAX_BYTES)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = ADJUST_LOG_MAX_BYTES
    return max(value, 1024)


def _trim_log_to_half_if_needed(path: Path, max_bytes: int) -> None:
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


def record_adjustment(ctx, event: str, pk: Any | None = None, **extra: Any) -> None:
    if not _enabled(ctx):
        return
    path = _adjust_log_path(ctx)
    max_bytes = _adjust_log_max_bytes(ctx)
    path.parent.mkdir(parents=True, exist_ok=True)
    _trim_log_to_half_if_needed(path, max_bytes)
    local_now = datetime.now().astimezone()
    record = {
        "ts": local_now.isoformat(),
        "timezone": local_now.tzname(),
        "event": event,
        "pid": os.getpid(),
        "mode": getattr(ctx, "mode", None),
        "task_json": task_json_name(ctx),
        "target": _target(ctx),
    }
    if pk is not None:
        record["pk"] = str(pk)
    record.update(extra)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    _trim_log_to_half_if_needed(path, max_bytes)


def _pid_is_alive(pid: Any) -> bool:
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return True
    if pid_int <= 0:
        return False
    if pid_int == os.getpid():
        return True
    try:
        os.kill(pid_int, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        # Windows may report an OSError for an invalid/non-running process.
        return False
    return True

def _ttl_seconds(ctx) -> float:
    raw = getattr(ctx, "pending_running_console_ttl_seconds", DEFAULT_TTL_SECONDS)
    try:
        return max(float(raw), 1.0)
    except (TypeError, ValueError):
        return float(DEFAULT_TTL_SECONDS)


def _lock_file(lock_fp: BinaryIO) -> None:
    if os.name == "nt":
        lock_fp.seek(0)
        msvcrt.locking(lock_fp.fileno(), msvcrt.LK_LOCK, 1)
        return
    fcntl.flock(lock_fp.fileno(), fcntl.LOCK_EX)


def _unlock_file(lock_fp: BinaryIO) -> None:
    if os.name == "nt":
        lock_fp.seek(0)
        msvcrt.locking(lock_fp.fileno(), msvcrt.LK_UNLCK, 1)
        return
    fcntl.flock(lock_fp.fileno(), fcntl.LOCK_UN)


@contextmanager
def _locked_json(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+b") as lock_fp:
        lock_fp.seek(0, os.SEEK_END)
        if lock_fp.tell() == 0:
            lock_fp.write(b"\0")
            lock_fp.flush()
        _lock_file(lock_fp)
        try:
            data = {"version": 1, "running": {}}
            if path.exists():
                try:
                    with path.open("r", encoding="utf-8") as fp:
                        loaded = json.load(fp)
                    if isinstance(loaded, dict):
                        data.update(loaded)
                        if not isinstance(data.get("running"), dict):
                            data["running"] = {}
                except Exception:
                    data = {"version": 1, "running": {}}
            yield data
            tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
            with tmp.open("w", encoding="utf-8") as fp:
                json.dump(data, fp, ensure_ascii=False, indent=2, sort_keys=True, default=str)
            os.replace(tmp, path)
        finally:
            _unlock_file(lock_fp)


def _target(ctx) -> str:
    for attr in (
        "_pending_tgt_table",
        "target_table",
        "current_output_path",
        "output_path",
        "output_excel_file",
        "output_csv_file",
        "llm_source_dir",
        "prompt_dir",
    ):
        value = getattr(ctx, attr, None)
        if value:
            return str(value)
    return ""


def _key(ctx, pk: Any) -> str:
    return f"{_target(ctx)}|{str(pk)}"


def _row_pk(row: Sequence[Any]) -> Any:
    return row[0]


def _prune(data: dict, ttl: float) -> None:
    now = time.time()
    running = data.setdefault("running", {})
    for key, rec in list(running.items()):
        try:
            ts = float(rec.get("updated_ts", rec.get("started_ts", 0)) or 0)
        except Exception:
            ts = 0.0
        if ts and now - ts > ttl:
            running.pop(key, None)
            continue
        if not _pid_is_alive(rec.get("pid")):
            running.pop(key, None)


def is_running(ctx, pk: Any) -> bool:
    if not _enabled(ctx):
        return False
    path = _console_path(ctx)
    with _locked_json(path) as data:
        _prune(data, _ttl_seconds(ctx))
        rec = data.get("running", {}).get(_key(ctx, pk))
        return bool(rec and rec.get("state") == "running")


def mark_running(ctx, pk: Any) -> None:
    if not _enabled(ctx):
        return
    path = _console_path(ctx)
    now = time.time()
    with _locked_json(path) as data:
        _prune(data, _ttl_seconds(ctx))
        data.setdefault("running", {})[_key(ctx, pk)] = {
            "state": "running",
            "pk": str(pk),
            "target": _target(ctx),
            "pid": os.getpid(),
            "task_json": task_json_name(ctx),
            "started_ts": now,
            "updated_ts": now,
        }


def mark_not_running(ctx, pk: Any, state: str = "completed") -> None:
    if not _enabled(ctx):
        return
    path = _console_path(ctx)
    with _locked_json(path) as data:
        _prune(data, _ttl_seconds(ctx))
        data.setdefault("running", {}).pop(_key(ctx, pk), None)
        data.setdefault("last_finished", {})[_key(ctx, pk)] = {
            "state": state,
            "pk": str(pk),
            "target": _target(ctx),
            "pid": os.getpid(),
            "task_json": task_json_name(ctx),
            "updated_ts": time.time(),
        }


def order_rows_avoiding_running(ctx, rows: Iterable[Sequence[Any]]) -> list[Sequence[Any]]:
    rows = list(rows)
    if not _enabled(ctx) or not rows:
        return rows
    path = _console_path(ctx)
    with _locked_json(path) as data:
        _prune(data, _ttl_seconds(ctx))
        running = data.get("running", {})
        cold: list[Sequence[Any]] = []
        hot: list[Sequence[Any]] = []
        for row in rows:
            (hot if running.get(_key(ctx, _row_pk(row)), {}).get("state") == "running" else cold).append(row)
    if hot:
        record_adjustment(ctx, "initial_reorder", deferred=len(hot), non_running=len(cold))
        tlog(
            "[producer] pending running console enabled: "
            f"defer running rows={len(hot)} after non-running rows={len(cold)}"
        )
    return cold + hot


def finalize_scheduled(ctx, scheduled_pks: Iterable[Any], pending_check=None) -> None:
    for pk in scheduled_pks:
        try:
            if pending_check is not None and not pending_check(ctx, pk):
                mark_not_running(ctx, pk, state="completed")
            else:
                mark_not_running(ctx, pk, state="released_pending")
        except Exception as exc:
            tlog_warn(f"[producer] pending running console finalize failed pk={pk}: {exc!r}")
