"""Best-effort, source-snapshotted observations of real queue file moves.

These event records are NOT a retry family, Worker invocation, provider HTTP
attempt, durable claim checkpoint, or unique-document denominator. A crash
between os.replace and recording can leave a real move with no observation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from uuid import uuid4

_ROOT = "_extract_slice_identity"
_KIND = "queue_events"
_EVENTS = {"claimed": "RUNNING", "requeued": "TODO"}
_UUID = re.compile(r"[0-9a-f]{32}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MAX_EVENT_BYTES = 1024
_MAX_EVENTS = 50000


def _safe_path(path: Path) -> bool:
    return not any(p.is_symlink() for p in (path, *path.parents))


def _source_snapshot(path: Path) -> tuple[str, int]:
    """Hash bytes through an actual regular-file descriptor without retaining input."""
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("queue source must be regular")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("queue source changed during open")
        digest = hashlib.sha256()
        total = 0
        while True:
            part = stream.read(65536)
            if not part:
                break
            total += len(part)
            digest.update(part)
        closed = os.fstat(stream.fileno())
    after = path.lstat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    if (not stat.S_ISREG(after.st_mode) or identity(before) != identity(opened)
            or identity(opened) != identity(closed) or identity(closed) != identity(after)
            or total != before.st_size):
        raise ValueError("queue source changed during hashing")
    return digest.hexdigest(), total


def record_queue_transition(path: str | Path, event: str, *, previous_path: str | Path | None = None) -> bool:
    """Observe a completed TODO/RUNNING move; never influence scheduler behavior.

    The old filename must be absent and new file must have the expected queue
    location; only the trusted scheduler calls this after successful os.replace.
    The source is checked *after* the move, and the append-only record is
    atomically published. No basename, path, prompt, endpoint or error is saved.
    """
    if event not in _EVENTS:
        raise ValueError("invalid queue transition")
    p = Path(path)
    if p.parent.name != _EVENTS[event] or p.suffix != ".txt":
        return False
    previous = Path(previous_path) if previous_path is not None else None
    if previous is None or previous.name != p.name:
        return False
    if not _safe_path(p) or not _safe_path(previous):
        return False
    root = p.parent.parent
    old_queue = "TODO" if event == "claimed" else "RUNNING"
    try:
        previous.relative_to(root / old_queue)
    except ValueError:
        return False
    if previous.exists() or previous.is_symlink():
        return False
    try:
        digest, size = _source_snapshot(p)
        namespace = p.parent.parent / _ROOT / _KIND
        if not _safe_path(namespace):
            return False
        namespace.mkdir(parents=True, exist_ok=True)
        if not _safe_path(namespace):
            return False
        event_id = uuid4().hex
        payload = {
            "version": 1, "event": event, "event_id": event_id,
            "source_sha256": digest, "source_bytes": size,
            "queue_name_sha256": hashlib.sha256(p.name.encode("utf-8")).hexdigest(),
            "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        data = (json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
        target = namespace / (event_id + ".json")
        temporary = namespace / (event_id + "." + uuid4().hex + ".tmp")
        if len(data) > _MAX_EVENT_BYTES:
            return False
        try:
            # A unique temporary name and exclusive publication prevent
            # overwriting another observation or accepting a partial JSON.
            with temporary.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            # The UUID is random, but don't overwrite if an attacker or an
            # unexpected collision already created this final name.
            if target.exists() or target.is_symlink():
                return False
            os.link(temporary, target, follow_symlinks=False)
        finally:
            temporary.unlink(missing_ok=True)
        return True
    except (OSError, ValueError, UnicodeError):
        return False


def summarize_queue_observations(item_dir: str | Path) -> dict[str, int]:
    """Bounded read-only observed counts, deliberately NOT retry statistics."""
    item = Path(item_dir)
    namespace = item / _ROOT / _KIND
    if not _safe_path(namespace):
        raise ValueError("queue observation namespace is aliased")
    if not namespace.exists():
        return {"observed_claims": 0, "observed_requeues": 0}
    if not namespace.is_dir():
        raise ValueError("invalid queue observation namespace")
    counts = {"claimed": 0, "requeued": 0}
    for index, path in enumerate(namespace.iterdir()):
        if index >= _MAX_EVENTS:
            raise ValueError("queue observation limit exceeded")
        if path.suffix != ".json" or not _UUID.fullmatch(path.stem) or not _safe_path(path):
            raise ValueError("invalid queue observation entry")
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_EVENT_BYTES:
            raise ValueError("invalid queue observation file")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as stream:
            opened = os.fstat(stream.fileno())
            data = stream.read(_MAX_EVENT_BYTES + 1)
            closed = os.fstat(stream.fileno())
        after = path.lstat()
        ident = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
        if (ident(info) != ident(opened) or ident(opened) != ident(closed)
                or ident(closed) != ident(after) or len(data) > _MAX_EVENT_BYTES):
            raise ValueError("queue observation changed during reading")
        try:
            record = json.loads(data)
        except (UnicodeError, ValueError, RecursionError) as exc:
            raise ValueError("invalid queue observation JSON") from exc
        if (not isinstance(record, dict) or
                set(record) != {"version", "event", "event_id", "source_sha256",
                                "source_bytes", "queue_name_sha256", "observed_at_utc"} or
                type(record["version"]) is not int or record["version"] != 1 or
                not isinstance(record["event"], str) or record["event"] not in counts or
                record["event_id"] != path.stem or
                not isinstance(record["source_sha256"], str) or not _SHA.fullmatch(record["source_sha256"]) or
                not isinstance(record["queue_name_sha256"], str) or not _SHA.fullmatch(record["queue_name_sha256"]) or
                type(record["source_bytes"]) is not int or record["source_bytes"] < 0 or
                not isinstance(record["observed_at_utc"], str)):
            raise ValueError("invalid queue observation schema")
        counts[record["event"]] += 1
    return {"observed_claims": counts["claimed"], "observed_requeues": counts["requeued"]}
