# -*- coding: utf-8 -*-
"""Explicit opt-in, bounded local-private JSON repair snapshots (sensitive).

Never log the raw strings to console, Quality JSONL, or the regular LLM audit.
This is a cooperating local-filesystem best effort, not encryption/hostile-writer
containment. Default capture OFF; Windows ACLs require operator verification.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from uuid import UUID

MAX_TEXT_CHARS = 80_000
MAX_FILE_BYTES = 512 * 1024
MAX_CASES_PER_RUN = 48
MAX_RUN_BYTES = 16 * 1024 * 1024
ENABLE_ENV = "CZJLLM_JSON_REPAIR_CAPTURE"
ROOT_ENV = "CZJLLM_JSON_REPAIR_PRIVATE_DIR"
_CASE_NAME = re.compile(r"^r-([0-9a-f]{32})\.json$")


def capture_enabled() -> bool:
    return os.environ.get(ENABLE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def configured_private_root() -> Path | None:
    raw = os.environ.get(ROOT_ENV, "").strip()
    return Path(raw) if raw else None


def _validate_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not (1 <= len(run_id) <= 96):
        raise ValueError("INVALID_RUN_ID")
    return hashlib.sha256(run_id.encode("utf-8")).hexdigest()


def _validate_event_id(event_id: str) -> str:
    if not isinstance(event_id, str) or not re.fullmatch("[0-9a-f]{32}", event_id):
        raise ValueError("INVALID_EVENT_ID")
    if UUID(hex=event_id).version != 4:
        raise ValueError("INVALID_EVENT_ID")
    return event_id


def _is_regular_private(path: Path, *, directory: bool):
    info = path.lstat()
    reparse = bool(getattr(info, "st_file_attributes", 0) &
                   getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    if reparse or stat.S_ISLNK(info.st_mode):
        raise ValueError("UNSAFE_FILE_TYPE")
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise ValueError("UNSAFE_FILE_TYPE")
    if not directory and info.st_nlink != 1:
        raise ValueError("UNSAFE_LINK_COUNT")
    return info


def _windows_local_fixed_drive(drive: str, *, drive_type=None) -> bool:
    """Reject UNC, mapped SMB, and unclassifiable volumes; no fail-open.

    GetDriveTypeW returns DRIVE_FIXED=3 for a local fixed drive and
    DRIVE_REMOTE=4 for mapped SMB. Native Windows ACLs still require
    separate operator approval before enabling plaintext capture.
    """
    if not re.fullmatch(r"[A-Za-z]:", drive):
        return False
    if drive_type is None:
        import ctypes
        try:
            drive_type = ctypes.windll.kernel32.GetDriveTypeW
        except (AttributeError, OSError):
            return False
    try:
        return drive_type(drive + "\\") == 3
    except (OSError, ValueError, TypeError):
        return False


_LOCAL_POSIX_FILESYSTEMS = frozenset({
    "ext2", "ext3", "ext4", "xfs", "btrfs", "zfs", "f2fs", "tmpfs",
})


def _posix_local_filesystem(path: Path, *, mountinfo: str | None = None) -> bool:
    """Fail closed on remote/unknown mount types using Linux mountinfo.

    A local-fs type is necessary, not sufficient proof of a private physical
    device (e.g., remote block devices and external backup are not excluded).
    The native workstation must still be operator verified.
    """
    if mountinfo is None:
        try:
            with open("/proc/self/mountinfo", encoding="utf-8") as handle:
                mountinfo = handle.read(1024 * 1024 + 1)
        except (OSError, UnicodeError):
            return False
        if len(mountinfo) > 1024 * 1024:
            return False
    target = os.path.normpath(str(path))
    best = (-1, "")
    for line in mountinfo.splitlines():
        left, separator, right = line.partition(" - ")
        if not separator:
            return False
        cols = left.split()
        tail = right.split()
        if len(cols) < 5 or len(tail) < 1:
            return False
        # Linux mountinfo escapes whitespace/control chars as octal.
        def unescape_mount(match):
            return chr(int(match.group(1), 8))
        mount_path = re.sub(r"\\([0-7]{3})", unescape_mount, cols[4])
        mount_path = os.path.normpath(mount_path)
        if not os.path.isabs(mount_path):
            return False
        try:
            if os.path.commonpath((target, mount_path)) != mount_path:
                continue
        except ValueError:
            return False
        depth = len(mount_path)
        if depth > best[0]:
            best = (depth, tail[0].lower())
        elif depth == best[0]:
            # Multiple entries at the same longest matching mountpoint can
            # represent stacked or bind mounts; their visible precedence
            # cannot be safely inferred from this simplified parser.
            # Fail closed regardless of filesystem type or listing order.
            best = (depth, "AMBIGUOUS_STACKED_MOUNT")
    return best[1] in _LOCAL_POSIX_FILESYSTEMS


def _root(root: Path | str) -> Path:
    raw = str(root)
    path = Path(root)
    if not path.is_absolute() or "\x00" in raw:
        raise ValueError("PRIVATE_DIR_NOT_ABSOLUTE")
    # Reject Windows UNC, mapped network names and POSIX-style // remotes.
    if raw.startswith(("//", "\\\\")):
        raise ValueError("NETWORK_ROOT_NOT_ALLOWED")
    if os.name == "nt" and not _windows_local_fixed_drive(path.drive):
        raise ValueError("WINDOWS_LOCAL_FIXED_VOLUME_REQUIRED")
    if os.name != "nt" and not _posix_local_filesystem(path):
        raise ValueError("POSIX_LOCAL_FILESYSTEM_UNVERIFIED")
    for candidate in (path, *path.parents):
        _is_regular_private(candidate, directory=True)
    if os.name != "nt" and (_is_regular_private(path, directory=True).st_mode & 0o077):
        raise ValueError("PRIVATE_DIR_PERMISSIONS")
    return path


def _run_dir(root: Path, run_digest: str) -> Path:
    sub = root / ("run-" + run_digest[:24])
    try:
        sub.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = _is_regular_private(sub, directory=True)
    # A remote filesystem may be mounted beneath a verified local root.
    # Inspect the actual snapshot/lock destination, not just its parent.
    if os.name != "nt" and not _posix_local_filesystem(sub):
        raise ValueError("POSIX_LOCAL_FILESYSTEM_UNVERIFIED")
    if os.name != "nt" and (info.st_mode & 0o077):
        raise ValueError("PRIVATE_RUN_PERMISSIONS")
    return sub


def _existing_run_dir(root: Path, run_digest: str) -> Path:
    sub = root / ("run-" + run_digest[:24])
    _is_regular_private(sub, directory=True)
    # Reads and manual deletion must obey the same nested-mount boundary.
    if os.name != "nt" and not _posix_local_filesystem(sub):
        raise ValueError("POSIX_LOCAL_FILESYSTEM_UNVERIFIED")
    return sub


@contextmanager
def _lock_run(folder: Path):
    lockpath = folder / ".capture.lock"
    # Windows Python lacks O_NOFOLLOW. Reject a preexisting reparse/symlink
    # BEFORE opening it, so initialization cannot modify another file.
    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    created = False
    try:
        before = _is_regular_private(lockpath, directory=False)
    except FileNotFoundError:
        try:
            fd = os.open(lockpath, flags | os.O_CREAT | os.O_EXCL, 0o600)
            created = True
        except FileExistsError:
            # A cooperative process won the create race; validate its name.
            before = _is_regular_private(lockpath, directory=False)
            fd = os.open(lockpath, flags)
    else:
        fd = os.open(lockpath, flags)
    try:
        info = os.fstat(fd)
        after_open = _is_regular_private(lockpath, directory=False)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or (info.st_dev, info.st_ino)
                != (after_open.st_dev, after_open.st_ino)
                or (not created and (before.st_dev, before.st_ino)
                    != (info.st_dev, info.st_ino))):
            raise ValueError("UNSAFE_LOCK")
        with os.fdopen(fd, "r+b", closefd=False) as handle:
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"0")
                handle.flush()
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _case_paths(folder: Path) -> list[Path]:
    paths = []
    for item in folder.iterdir():
        if item.name == ".capture.lock":
            _is_regular_private(item, directory=False)
            continue
        if not _CASE_NAME.fullmatch(item.name):
            raise ValueError("UNKNOWN_PRIVATE_ARTIFACT")
        _is_regular_private(item, directory=False)
        paths.append(item)
    return paths


def write_private_repair(
    root: Path | str, run_id: str, event_id: str,
    original: str, repaired: str,
) -> bool:
    """Fail closed and let the caller catch fixed-code errors; never overwrite."""
    digest = _validate_run_id(run_id)
    event_id = _validate_event_id(event_id)
    if (not isinstance(original, str) or not isinstance(repaired, str)
            or len(original) > MAX_TEXT_CHARS or len(repaired) > MAX_TEXT_CHARS):
        raise ValueError("PRIVATE_TEXT_OVER_LIMIT")
    payload = json.dumps({
        "schema_version": 1, "event_id": event_id, "run_digest": digest,
        "original": original, "repaired": repaired,
    }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_FILE_BYTES:
        raise ValueError("PRIVATE_BYTES_OVER_LIMIT")
    folder = _run_dir(_root(root), digest)
    target = folder / ("r-" + event_id + ".json")
    with _lock_run(folder):
        existing = _case_paths(folder)
        if len(existing) >= MAX_CASES_PER_RUN or sum(
            x.stat().st_size for x in existing
        ) + len(payload) > MAX_RUN_BYTES:
            raise ValueError("PRIVATE_RUN_BUDGET")
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(target, flags, 0o600)
        try:
            # closefd=True makes the handle close even when flush/fsync raises.
            with os.fdopen(fd, "wb") as handle:
                fd = None
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            # Windows denies unlink of a still-open CRT descriptor. Close
            # before deleting partial sensitive plaintext on failure.
            if fd is not None:
                os.close(fd)
            try:
                target.unlink()
            except OSError:
                pass
            raise
    return True


def read_private_repair(root: Path | str, run_id: str, event_id: str) -> dict:
    """Explicit-view only; never return source path or read another run."""
    digest = _validate_run_id(run_id)
    event_id = _validate_event_id(event_id)
    folder = _existing_run_dir(_root(root), digest)
    path = folder / ("r-" + event_id + ".json")
    before = _is_regular_private(path, directory=False)
    if before.st_size > MAX_FILE_BYTES or before.st_size < 2:
        raise ValueError("PRIVATE_READ_BUDGET")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags)
    try:
        current = os.fstat(fd)
        if (not stat.S_ISREG(current.st_mode) or current.st_nlink != 1
                or (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
                != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)):
            raise ValueError("PRIVATE_CHANGED")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            payload = handle.read(MAX_FILE_BYTES + 1)
        after = _is_regular_private(path, directory=False)
        if (len(payload) != before.st_size or len(payload) > MAX_FILE_BYTES
                or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)):
            raise ValueError("PRIVATE_CHANGED")
    finally:
        os.close(fd)
    record = json.loads(payload.decode("utf-8"))
    if (not isinstance(record, dict) or set(record) != {
            "schema_version", "event_id", "run_digest", "original", "repaired",
        } or record["schema_version"] != 1
            or record["event_id"] != event_id or record["run_digest"] != digest
            or not isinstance(record["original"], str)
            or not isinstance(record["repaired"], str)
            or len(record["original"]) > MAX_TEXT_CHARS
            or len(record["repaired"]) > MAX_TEXT_CHARS):
        raise ValueError("PRIVATE_CONTENT_INVALID")
    return {"original": record["original"], "repaired": record["repaired"]}


def clear_private_run(root: Path | str, run_id: str, confirmation: str) -> int:
    """Manual confirmation; clears only this run's exact capture files."""
    if confirmation != "DELETE_PRIVATE_JSON_REPAIRS":
        raise ValueError("CONFIRMATION_REQUIRED")
    folder = _existing_run_dir(_root(root), _validate_run_id(run_id))
    with _lock_run(folder):
        cases = _case_paths(folder)
        for item in cases:
            _is_regular_private(item, directory=False)
            item.unlink()
        return len(cases)
