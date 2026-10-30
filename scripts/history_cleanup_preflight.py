#!/usr/bin/env python3
"""Read-only, redacted preflight for a future Git history rewrite.

No branches, tags, objects, or remotes are changed. No secret content is read.
This is not a substitute for rotation, a full history scan, or owner approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys

# Known public paths; never embed credential VALUES or historical blob content.
LEGACY_PATHS = (
    "czjLLM/czjLLM_utils_key.py",
    "czjLLM/__pycache__/DeepSeek_utils_key.cpython-311.pyc",
    "czjLLM/__pycache__/czjLLM_utils_key.cpython-311.pyc",
)
SQL_CONFIG_PATHS = (
    "czjLLM/config_sql/akconfig_test.py",
    "czjLLM/config_sql/akconfig_test_to_excel.py",
    "czjLLM/config_sql/akconfig_test_SRP.py",
    "czjLLM/config_sql/akconfig_test_SRP - 複製.py",
)
SHA = re.compile(r"[0-9a-f]{40}\Z")


def git(*args: str, cwd=None) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True
    ).stdout


def preflight(expected_main: str, cwd=None) -> dict:
    if not SHA.fullmatch(expected_main):
        raise ValueError("expected main must be exactly 40 lower-case hex digits")
    actual_main = git("rev-parse", "refs/remotes/origin/main", cwd=cwd).decode().strip()
    if actual_main != expected_main:
        raise ValueError("main HEAD differs from expected SHA; freeze/refresh approval")
    branch_output = git(
        "for-each-ref", "--format=%(refname)%00%(objectname)",
        "refs/remotes/origin/", cwd=cwd,
    ).splitlines()
    branches: list[tuple[str, str]] = []
    for item in branch_output:
        ref, oid = item.decode("utf-8").split("\0", 1)
        if ref == "refs/remotes/origin/HEAD":
            continue
        if not SHA.fullmatch(oid):
            raise ValueError("invalid branch object id")
        branches.append((ref, oid))
    if not branches or "refs/remotes/origin/main" not in [x[0] for x in branches]:
        raise ValueError("no authoritative remote main branch found")
    # Snapshot ALL fetched tags too, retaining the tag object's own SHA.
    # Never dereference annotated tags: that would miss a tag-object replacement
    # if the peeled target happened to remain unchanged.
    tag_output = git(
        "for-each-ref", "--format=%(refname)%00%(objectname)",
        "refs/tags/", cwd=cwd,
    ).splitlines()
    tags: list[tuple[str, str]] = []
    for item in tag_output:
        ref, oid = item.decode("utf-8").split("\0", 1)
        if not ref.startswith("refs/tags/") or not SHA.fullmatch(oid):
            raise ValueError("invalid tag ref or object id")
        tags.append((ref, oid))
    # Fully qualified ref names avoid branch/tag namespace ambiguity.
    # Commit/tag object identifiers are public Git metadata, not credentials.
    all_refs = sorted(branches + tags)
    refs_sha = hashlib.sha256(
        "".join(ref + "\0" + oid + "\n" for ref, oid in all_refs).encode()
    ).hexdigest()
    tracked_path_counts: dict[str, int] = {}
    for path in LEGACY_PATHS + SQL_CONFIG_PATHS:
        count = 0
        for ref, _ in branches:
            # Object/path existence only; do not fetch or log any file bytes.
            if git("ls-tree", "--name-only", ref, "--", path, cwd=cwd).strip():
                count += 1
        tracked_path_counts[path] = count
    return {
        "schema": "history-cleanup-preflight-v2",
        "mode": "READ_ONLY",
        "expected_main": expected_main,
        "remote_branch_count": len(branches),
        "tag_count": len(tags),
        "remote_ref_snapshot_sha256": refs_sha,
        "known_paths_in_branch_heads": tracked_path_counts,
        "candidate_legacy_path_count": len(LEGACY_PATHS),
        "pending_individual_sql_redaction": len(SQL_CONFIG_PATHS),
        "blockers": [
            "provider-side key and SQL credential revocation not independently confirmed",
            "SQL history requires secret-safe replacement, not blanket deletion of sanitized live config",
            "complete full-history scan including oversized blobs, forks, PR refs and CI logs not completed",
            "private verified backup and contributor freeze not completed",
            "explicit scope-specific authorization for remote ref changes not granted",
        ],
        "writes_git_references": False,
        "contains_secret_values": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-main", required=True, help="Expected exact remote main commit SHA")
    args = parser.parse_args()
    try:
        result = preflight(args.expected_main)
    except (ValueError, subprocess.CalledProcessError, UnicodeError, OSError):
        # Never echo subprocess stderr: it may include sensitive config or path data.
        print("History cleanup preflight blocked: stale or unavailable ref snapshot.", file=sys.stderr)
        return 2
    print("REDACTED_HISTORY_CLEANUP_PREFLIGHT=" + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
