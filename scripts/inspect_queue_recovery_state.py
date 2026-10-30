#!/usr/bin/env python3
"""Metadata-only, no-follow queue diagnostic, not permission to replay files.

This does not lock producers or acquire an atomic filesystem snapshot.
On platforms lacking verified handle-relative, no-follow directory traversal
(including supported Windows Python builds), fail CLOSED instead of guessing.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat


ROLES = ("TODO", "RUNNING", "Success", ".success-publish-staging")
MAX_ITEMS = 100
DEFAULT_MAX_ENTRIES = 10000
FILE_ATTRIBUTE_REPARSE_POINT = 0x400


class _UnsafeScan(Exception):
    """A filesystem tree was unsafe or could not be completely enumerated."""


class _UnsupportedSafeScan(Exception):
    """The platform cannot guarantee no-follow traversal."""


def _supports_safe_scan() -> bool:
    """Require atomic no-follow opens and fd-relative metadata/enumeration."""
    return (
        os.name == "posix"
        and hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY")
        and os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
        and os.scandir in os.supports_fd
    )


def _is_reparse_point(info: os.stat_result) -> bool:
    """Refuse Windows junctions/reparse points even if they look like dirs."""
    return bool(getattr(info, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT)


def _identity(info: os.stat_result) -> tuple[int, int] | None:
    """Unknown identities must never compare as the same inode (e.g. 0, 0)."""
    dev = getattr(info, "st_dev", None)
    ino = getattr(info, "st_ino", None)
    links = getattr(info, "st_nlink", None)
    if not all(type(x) is int and x > 0 for x in (dev, ino, links)):
        return None
    return (dev, ino)


def _open_directory(parent_fd: int, name: str) -> int:
    """Open exactly one directory child without following a reparse/symlink."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    fd = os.open(name, flags, dir_fd=parent_fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or _is_reparse_point(info):
            raise _UnsafeScan
        return fd
    except BaseException:
        os.close(fd)
        raise


@contextmanager
def _open_item_root(directory: Path):
    """Pin each ancestor one by one, never open a full replaceable path."""
    # Reject parent traversal BEFORE abspath() can collapse unvalidated
    # ancestors. For example, alias/../item must never silently become item
    # when alias is a symlink, dangling directory or replaced junction.
    raw = Path(directory)
    if ".." in raw.parts:
        raise _UnsafeScan
    # From here, an absolute lexical path contains no parent traversal.
    # Pin every remaining component with a handle-relative O_NOFOLLOW open.
    root = Path(os.path.abspath(os.fspath(raw)))
    if root.anchor != os.sep:
        raise _UnsafeScan
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    fd = os.open(root.anchor, flags)
    try:
        for part in root.parts[1:]:
            next_fd = _open_directory(fd, part)
            os.close(fd)
            fd = next_fd
        yield fd
    finally:
        os.close(fd)


def _scan_tree(root_fd: int, role: str, seen: list[int], limit: int):
    """Stream bounded entries using directory FDs: no path-based scandir."""
    regular = []
    unsafe = 0
    unknown_identity = 0
    try:
        directory_fd = _open_directory(root_fd, role)
    except FileNotFoundError:
        return regular, unsafe, unknown_identity

    # Every opened directory is owned by this stack. A race replacing a
    # child with a symlink cannot redirect a handle-relative O_NOFOLLOW open.
    stack = [(directory_fd, ())]
    try:
        while stack:
            directory_fd, relative = stack.pop()
            try:
                with os.scandir(directory_fd) as iterator:
                    for entry in iterator:
                        seen[0] += 1
                        # Apply the cap WHILE reading, before sorting or
                        # materializing an untrusted directory's entries.
                        if seen[0] > limit:
                            raise _UnsafeScan
                        # DirEntry.stat on Windows can report zero identity
                        # fields; use handle-relative os.stat instead.
                        info = os.stat(
                            entry.name, dir_fd=directory_fd,
                            follow_symlinks=False,
                        )
                        parts = relative + (entry.name,)
                        if _is_reparse_point(info):
                            unsafe += 1
                        elif stat.S_ISDIR(info.st_mode):
                            child_fd = _open_directory(directory_fd, entry.name)
                            current = os.fstat(child_fd)
                            if (_identity(info) is None
                                    or _identity(current) != _identity(info)):
                                os.close(child_fd)
                                raise _UnsafeScan
                            stack.append((child_fd, parts))
                        elif stat.S_ISREG(info.st_mode):
                            key = _identity(info)
                            if key is None:
                                unknown_identity += 1
                            regular.append((parts, key, info.st_nlink))
                        else:
                            unsafe += 1
            finally:
                os.close(directory_fd)
        return regular, unsafe, unknown_identity
    finally:
        # Clean up FDs for unvisited descendants on any error/cap overflow.
        for fd, _parts in stack:
            os.close(fd)


def _is_windows() -> bool:
    return os.name == "nt"


def _native_windows_snapshot(item_dir, max_entries):
    # Lazy import: POSIX production remains entirely independent of Win32.
    from scripts.queue_win32_native_enumeration import scan_windows_roles
    return scan_windows_roles(item_dir, max_entries)


def inspect_item(item_dir: Path, *, max_entries: int = DEFAULT_MAX_ENTRIES,
                 experimental_windows: bool = False) -> dict:
    """Non-atomic count-only snapshot; no source bytes or names in output.

    Windows scan requires explicit opt-in and ALWAYS returns review_required
    until genuine native Windows acceptance is established. No safe-replay
    implication is permitted, even when no conflicts are observed.
    """
    counts = {key: 0 for key in (
        "todo_files", "running_files", "success_files", "staging_files",
        "duplicate_todo_basename_groups", "todo_running_basename_overlaps",
        "todo_success_basename_overlaps", "running_success_basename_overlaps",
        "todo_running_shared_inode_groups", "multiply_linked_queue_entries",
        "unknown_identity_entries", "staging_temp_files",
        "staging_other_files", "unsafe_entries",
    )}
    result = {"scan_complete": False, "status": "review_required",
              "counts": counts, "codes": []}
    if not 1 <= max_entries <= 100000:
        result["codes"].append("INVALID_ENTRY_LIMIT")
        return result
    native_windows = _is_windows()
    if native_windows:
        if not experimental_windows:
            result["codes"].append("UNSUPPORTED_SAFE_SCAN_PLATFORM")
            return result
        try:
            role_files, unsafe, unknown_identity = _native_windows_snapshot(
                item_dir, max_entries
            )
        except (OSError, ValueError, RuntimeError, RecursionError):
            # A controlled exception may contain private path details from
            # the kernel. Never copy its message into the operator report.
            result["codes"].append("INCOMPLETE_OR_UNSAFE_SCAN")
            return result
    else:
        if not _supports_safe_scan():
            result["codes"].append("UNSUPPORTED_SAFE_SCAN_PLATFORM")
            return result
        try:
            seen = [0]
            with _open_item_root(Path(item_dir)) as root_fd:
                role_files = {}
                unsafe = unknown_identity = 0
                for role in ROLES:
                    files, unsafes, unknowns = _scan_tree(
                        root_fd, role, seen, max_entries
                    )
                    role_files[role] = files
                    unsafe += unsafes
                    unknown_identity += unknowns
        except (OSError, ValueError, _UnsafeScan, RecursionError):
            result["codes"].append("INCOMPLETE_OR_UNSAFE_SCAN")
            return result

    todo, running, success, staging = (role_files[r] for r in ROLES)
    counts["todo_files"] = len(todo)
    counts["running_files"] = len(running)
    counts["success_files"] = len(success)
    counts["staging_files"] = len(staging)
    # Windows queue basenames can compare case-insensitively. Do not miss
    # conflicts such as TODO/Root.txt versus Success/root.txt.
    normalize = str.casefold if native_windows else str
    names = [Counter(normalize(parts[-1]) for parts, _, _ in entries)
             for entries in (todo, running, success)]
    counts["duplicate_todo_basename_groups"] = sum(
        frequency > 1 for frequency in names[0].values()
    )
    counts["todo_running_basename_overlaps"] = len(names[0].keys() & names[1].keys())
    counts["todo_success_basename_overlaps"] = len(names[0].keys() & names[2].keys())
    counts["running_success_basename_overlaps"] = len(names[1].keys() & names[2].keys())
    todo_inodes = {key for _, key, _ in todo if key is not None}
    run_inodes = {key for _, key, _ in running if key is not None}
    counts["todo_running_shared_inode_groups"] = len(todo_inodes & run_inodes)
    counts["multiply_linked_queue_entries"] = sum(
        links > 1 for entries in (todo, running, success)
        for _, key, links in entries if key is not None
    )
    counts["unknown_identity_entries"] = unknown_identity
    counts["staging_temp_files"] = sum(
        parts[-1].startswith(".success-") and parts[-1].endswith(".tmp")
        for parts, _, _ in staging
    )
    counts["staging_other_files"] = len(staging) - counts["staging_temp_files"]
    counts["unsafe_entries"] = unsafe
    code_by_count = (
        ("duplicate_todo_basename_groups", "DUPLICATE_TODO_BASENAME"),
        ("todo_running_basename_overlaps", "TODO_RUNNING_NAME_OVERLAP"),
        ("todo_success_basename_overlaps", "TODO_SUCCESS_CONFLICT"),
        ("running_success_basename_overlaps", "RUNNING_SUCCESS_OVERLAP"),
        ("todo_running_shared_inode_groups", "POSSIBLE_INTERRUPTED_LINK_MOVE"),
        ("multiply_linked_queue_entries", "MULTILINK_QUEUE_ENTRY"),
        ("unknown_identity_entries", "UNKNOWN_FILE_IDENTITY"),
        ("staging_temp_files", "STAGING_TEMP_PRESENT"),
        ("staging_other_files", "UNEXPECTED_STAGING_FILE"),
        ("unsafe_entries", "UNSAFE_ENTRY_PRESENT"),
    )
    result["codes"] = [code for name, code in code_by_count if counts[name]]
    if native_windows:
        # Deliberately prevent an unverified Windows run from claiming clean
        # status or allowing exit 0 before self-hosted real filesystem proof.
        result["codes"].append("WINDOWS_EXPERIMENTAL_UNVERIFIED")
    result["scan_complete"] = True
    result["status"] = "review_required" if result["codes"] else "no_observed_conflicts"
    return result


def inspect_items(item_dirs, *, max_entries: int = DEFAULT_MAX_ENTRIES,
                  experimental_windows: bool = False) -> dict:
    """Ordinal-only summaries. Scan does not acquire a cross-process lock."""
    results = []
    for idx, directory in enumerate(item_dirs, 1):
        row = inspect_item(Path(directory), max_entries=max_entries,
                           experimental_windows=experimental_windows)
        row["item"] = idx
        results.append(row)
    return {
        "version": 1,
        "mode": "read_only_non_atomic",
        "items": results,
        "all_snapshots_complete": all(r["scan_complete"] for r in results),
        "manual_review_required": any(r["status"] != "no_observed_conflicts"
                                       for r in results),
        "warning": (
            "A clear snapshot does not prove completion, writer quiescence, "
            "source generation or safe replay. No file was modified."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--item-dir", action="append", required=True,
                        help="Item root containing TODO/RUNNING/Success; repeatable")
    parser.add_argument("--max-entries", type=int, default=DEFAULT_MAX_ENTRIES,
                        help="Fail closed if one item contains more entries (default: 10000)")
    parser.add_argument(
        "--experimental-windows", action="store_true",
        help="Native Windows metadata-only probe; always review-required/exit 2",
    )
    args = parser.parse_args()
    if len(args.item_dir) > MAX_ITEMS:
        print(json.dumps({"version": 1, "error": "TOO_MANY_ITEMS"}))
        return 2
    try:
        report = inspect_items(
            args.item_dir, max_entries=args.max_entries,
            experimental_windows=args.experimental_windows,
        )
    except (OSError, ValueError):
        print(json.dumps({"version": 1, "error": "INSPECTION_FAILED"}))
        return 2
    print(json.dumps(report, sort_keys=True, ensure_ascii=True))
    return 2 if report["manual_review_required"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
