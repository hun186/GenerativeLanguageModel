#!/usr/bin/env python3
"""Read-only queue artifact inventory; no prompt contents or paths in output.

This is a NON-ATOMIC snapshot, not permission to replay, unlink or recover.
Stop all producers/workers before using it for a human recovery decision.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import stat


ROLES = ("TODO", "RUNNING", "Success", ".success-publish-staging")
MAX_ITEMS = 100
DEFAULT_MAX_ENTRIES = 10000


class _UnsafeScan(Exception):
    """One filesystem tree could not be safely or fully enumerated."""


def _inode_key(info: os.stat_result) -> tuple[int, int]:
    return (info.st_dev, info.st_ino)


def _scan_tree(directory: Path, seen: list[int], limit: int):
    """List regular files only. Never follow directory or file symlinks."""
    regular = []
    unsafe = 0
    try:
        status = directory.lstat()
    except FileNotFoundError:
        # A missing role directory is an empty role, not a missing item.
        return regular, unsafe
    except OSError as exc:
        raise _UnsafeScan from exc
    if not stat.S_ISDIR(status.st_mode):
        raise _UnsafeScan

    stack = [(directory, ())]
    while stack:
        current, relative = stack.pop()
        try:
            with os.scandir(current) as iterator:
                children = sorted(iterator, key=lambda entry: entry.name)
            for entry in children:
                seen[0] += 1
                if seen[0] > limit:
                    raise _UnsafeScan
                info = entry.stat(follow_symlinks=False)
                relative_parts = relative + (entry.name,)
                if stat.S_ISDIR(info.st_mode):
                    stack.append((Path(entry.path), relative_parts))
                elif stat.S_ISREG(info.st_mode):
                    regular.append((relative_parts, _inode_key(info), info.st_nlink))
                else:
                    # Symlinks, junctions, pipes, sockets and special entries
                    # are NEVER traversed. Their names do not appear in output.
                    unsafe += 1
        except (OSError, ValueError) as exc:
            raise _UnsafeScan from exc
    return regular, unsafe


def inspect_item(item_dir: Path, *, max_entries: int = DEFAULT_MAX_ENTRIES) -> dict:
    """Return only numeric counts and fixed codes, never a path or file data."""
    counts = {key: 0 for key in (
        "todo_files", "running_files", "success_files", "staging_files",
        "duplicate_todo_basename_groups", "todo_running_basename_overlaps",
        "todo_success_basename_overlaps", "running_success_basename_overlaps",
        "todo_running_shared_inode_groups", "multiply_linked_queue_entries",
        "staging_temp_files", "staging_other_files", "unsafe_entries",
    )}
    result = {"scan_complete": False, "status": "review_required",
              "counts": counts, "codes": []}
    if not 1 <= max_entries <= 100000:
        result["codes"].append("INVALID_ENTRY_LIMIT")
        return result
    # Never resolve() into an unknown external directory: symlinked ancestors
    # are refused, and no queue file is opened/read.
    try:
        root = Path(item_dir).absolute()
        if any(p.is_symlink() for p in (root, *root.parents)):
            raise _UnsafeScan
        if not stat.S_ISDIR(root.lstat().st_mode):
            raise _UnsafeScan
        seen = [0]
        role_files = {}
        unsafe = 0
        for role in ROLES:
            role_files[role], extra = _scan_tree(root / role, seen, max_entries)
            unsafe += extra
    except (OSError, ValueError, _UnsafeScan):
        result["codes"].append("INCOMPLETE_OR_UNSAFE_SCAN")
        return result

    todo, running, success, staging = (role_files[r] for r in ROLES)
    counts["todo_files"] = len(todo)
    counts["running_files"] = len(running)
    counts["success_files"] = len(success)
    counts["staging_files"] = len(staging)
    names = [Counter(parts[-1] for parts, _, _ in entries)
             for entries in (todo, running, success)]
    counts["duplicate_todo_basename_groups"] = sum(
        frequency > 1 for frequency in names[0].values()
    )
    counts["todo_running_basename_overlaps"] = len(names[0].keys() & names[1].keys())
    counts["todo_success_basename_overlaps"] = len(names[0].keys() & names[2].keys())
    counts["running_success_basename_overlaps"] = len(names[1].keys() & names[2].keys())
    todo_inodes = {_inode for _, _inode, _ in todo}
    run_inodes = {_inode for _, _inode, _ in running}
    counts["todo_running_shared_inode_groups"] = len(todo_inodes & run_inodes)
    counts["multiply_linked_queue_entries"] = sum(
        links > 1 for entries in (todo, running, success)
        for _, _, links in entries
    )
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
        ("staging_temp_files", "STAGING_TEMP_PRESENT"),
        ("staging_other_files", "UNEXPECTED_STAGING_FILE"),
        ("unsafe_entries", "UNSAFE_ENTRY_PRESENT"),
    )
    result["codes"] = [code for name, code in code_by_count if counts[name]]
    result["scan_complete"] = True
    result["status"] = "review_required" if result["codes"] else "no_observed_conflicts"
    return result


def inspect_items(item_dirs, *, max_entries: int = DEFAULT_MAX_ENTRIES) -> dict:
    """Ordinal-only summaries. Scan does not acquire a cross-process lock."""
    results = []
    for idx, directory in enumerate(item_dirs, 1):
        row = inspect_item(Path(directory), max_entries=max_entries)
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
    args = parser.parse_args()
    if len(args.item_dir) > MAX_ITEMS:
        print(json.dumps({"version": 1, "error": "TOO_MANY_ITEMS"}))
        return 2
    try:
        report = inspect_items(args.item_dir, max_entries=args.max_entries)
    except (OSError, ValueError):
        print(json.dumps({"version": 1, "error": "INSPECTION_FAILED"}))
        return 2
    print(json.dumps(report, sort_keys=True, ensure_ascii=True))
    return 2 if report["manual_review_required"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
