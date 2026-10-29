#!/usr/bin/env python3
"""Read-only redacted audit of credential-like patterns in reachable Git blobs.

No credential values, excerpts, fingerprints, or raw blobs are logged.
Requires all desired remote heads and tags to be fetched.
Does NOT assess provider validity, forks, CI logs or unreachable objects.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
import re
import subprocess
import sys

MAX_BYTES = 2_000_000
KEY = re.compile(rb"(?<![A-Za-z0-9])" + b"sk" + rb"-[A-Za-z0-9_-]{20,}")
ASSIGN = re.compile(
    rb"\b(?:password|passwd|api[_-]?key|access[_-]?token|auth[_-]?token|secret)\s*[:=]\s*['\"]([^'\"\r\n]{6,})['\"]", re.I
)
PRIVATE = re.compile(rb"-----BEGIN (?:RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----")
PLACEHOLDER = re.compile(rb"^(?:example|sample|placeholder|redacted|dummy|changeme|your[_-]|test[_-])", re.I)


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout


def classify(data):
    categories = set()
    if KEY.search(data):
        categories.add("key_style")
    if PRIVATE.search(data):
        categories.add("private_key_header")
    for match in ASSIGN.finditer(data):
        if not PLACEHOLDER.match(match.group(1)):
            categories.add("credential_assignment")
            break
    return categories


def read_object(stream, size, retain):
    chunks = []
    remaining = size
    while remaining:
        chunk = stream.read(min(remaining, 65536))
        if not chunk:
            raise RuntimeError("unexpected Git object EOF")
        if retain:
            chunks.append(chunk)
        remaining -= len(chunk)
    if stream.read(1) != b"\n":
        raise RuntimeError("malformed Git object delimiter")
    return b"".join(chunks) if retain else b""


def audit():
    objects = git("rev-list", "--objects", "--all").splitlines()
    refs = git("for-each-ref", "--format=%(refname)").splitlines()
    remote_heads = git(
        "for-each-ref", "--format=%(refname)", "refs/remotes/origin"
    ).splitlines()
    key_path = "czjLLM/czjLLM_utils_key.py"
    exposed_branch_heads = 0
    for remote_ref in remote_heads:
        # Check the published HEAD of each branch without reading its content.
        if git("ls-tree", "-r", "--name-only", remote_ref.decode("ascii"), "--", key_path).strip():
            exposed_branch_heads += 1
    proc = subprocess.Popen(
        ["git", "cat-file", "--batch"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    assert proc.stdin is not None and proc.stdout is not None
    counts, patterns, pyc_patterns = Counter(), Counter(), Counter()
    try:
        for item in objects:
            oid = item.split(b" ", 1)[0]
            proc.stdin.write(oid + b"\n")
            proc.stdin.flush()
            header = proc.stdout.readline().strip().split(b" ")
            if len(header) != 3 or header[0] != oid:
                raise RuntimeError("invalid Git cat-file response")
            kind, size = header[1], int(header[2])
            retain = kind == b"blob" and size <= MAX_BYTES
            payload = read_object(proc.stdout, size, retain)
            counts["reachable_git_objects"] += 1
            if kind != b"blob":
                continue
            counts["reachable_blob_objects"] += 1
            path = item.split(b" ", 1)[1] if b" " in item else b""
            is_pyc = path.lower().endswith(b".pyc")
            if is_pyc:
                counts["compiled_python_blob_objects"] += 1
            if not retain:
                counts["oversize_blob_objects_not_scanned"] += 1
                continue
            counts["inspected_blob_objects"] += 1
            categories = classify(payload)
            if categories:
                counts["matched_blob_objects"] += 1
                for category in categories:
                    patterns[category] += 1
                    if is_pyc:
                        pyc_patterns[category] += 1
    finally:
        proc.stdin.close()
        proc.stdout.close()
        proc.wait(timeout=15)
    return {
        "audit_version": 1,
        "scope": "reachable Git objects from fetched local and remote refs",
        "ref_count": len(refs),
        "fetched_remote_branch_heads": len(remote_heads),
        "branch_heads_still_containing_legacy_key_file": exposed_branch_heads,
        "counts": dict(counts),
        "credential_pattern_blob_counts": dict(patterns),
        "compiled_python_pattern_blob_counts": dict(pyc_patterns),
        "limitations": [
            "pattern-based and non-exhaustive; false positives possible",
            "does not scan forks, unreachable objects, GitHub Actions logs or artifacts",
            "does not scan blobs above two million bytes",
            "does not determine provider validity, unauthorized use or revocation",
        ],
        "contains_raw_secrets": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        sample = b"sk" + b"-" + b"A" * 29
        assert "key_style" in classify(sample)
        synthetic_assignment = b"pass" + b"word = " + b"'synthetic_for_regression'"
        assert "credential_assignment" in classify(synthetic_assignment)
        assert not classify(b"password = os.environ.get('SQL_PASSWORD')")
        assert not classify(b"api_key = 'placeholder-value'")
        assert "private_key_header" in classify(b"-----BEGIN " + b"PRIVATE KEY-----")
        print("Synthetic secret scanner tests: PASS")
        return 0
    try:
        result = audit()
    except (subprocess.CalledProcessError, OSError, RuntimeError):
        print("Git history audit failed; diagnostic content suppressed.", file=sys.stderr)
        return 2
    print("REDACTED_GIT_HISTORY_AUDIT=" + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
