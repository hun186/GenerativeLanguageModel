"""Opt-in SHA-256 consistency ledger for stopped-producer quality JSONL archives.

This is an accidental-loss/corruption detector, NOT a signed or authenticated
audit log. A person able to alter both the archives and the manifest can
recompute matching hashes. An initially missing ledger cannot prove history.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
from uuid import uuid4

from czjLLM.utilities.processing_quality import (
    _lock_stream, _unlock_stream, quality_event_path,
)
from czjLLM.utilities.processing_quality_rotation import (
    MAX_QUALITY_SEGMENTS, quality_stream_segments,
)

_MANIFEST_VERSION = 1
_MAX_MANIFEST_BYTES = 24 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def manifest_path(active: str | Path) -> Path:
    return Path(str(active) + ".manifest.json")


def _is_link(info) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _regular_snapshot(path: Path) -> tuple[os.stat_result, bytes]:
    """Hash a fixed descriptor in chunks with pathname/size/mtime checks."""
    original = path.lstat()
    if _is_link(original) or not stat.S_ISREG(original.st_mode):
        raise ValueError("quality archive is not a regular file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as fp:
        opened = os.fstat(fp.fileno())
        if (original.st_dev, original.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError("quality archive changed during open")
        digest = hashlib.sha256()
        total = 0
        last_byte = b""
        while True:
            chunk = fp.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            digest.update(chunk)
            last_byte = chunk[-1:]
        closed = os.fstat(fp.fileno())
    after = path.lstat()
    if (_is_link(after) or
            (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
            != (closed.st_dev, closed.st_ino, closed.st_size, closed.st_mtime_ns) or
            (original.st_dev, original.st_ino, original.st_size, original.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) or
            total != opened.st_size):
        raise ValueError("quality archive changed during hashing")
    if not total or last_byte != b"\n":
        raise ValueError("quality archive has empty or incomplete content")
    return opened, digest.digest()


def segment_fingerprint(segment: Path, index: int) -> dict:
    info, digest = _regular_snapshot(segment)
    return {
        "sequence": index,
        "bytes": info.st_size,
        "sha256": digest.hex(),
    }


def _canonical(entries: list[dict]) -> bytes:
    return json.dumps(
        entries, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")


def _manifest_document(entries: list[dict]) -> dict:
    return {
        "schema_version": _MANIFEST_VERSION,
        "segments": entries,
        "ledger_sha256": hashlib.sha256(_canonical(entries)).hexdigest(),
    }


def _read_manifest(path: Path) -> dict | None:
    if path.is_symlink():
        raise ValueError("quality manifest must not be a symlink")
    if not path.exists():
        return None
    raw_info = path.lstat()
    if _is_link(raw_info) or not stat.S_ISREG(raw_info.st_mode):
        raise ValueError("quality manifest must be regular")
    if raw_info.st_size > _MAX_MANIFEST_BYTES:
        raise ValueError("quality manifest too large")
    # Bound the read even if an external process appends between stat/open.
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as fp:
        opened = os.fstat(fp.fileno())
        if (opened.st_dev, opened.st_ino) != (raw_info.st_dev, raw_info.st_ino):
            raise ValueError("quality manifest changed during open")
        data = fp.read(_MAX_MANIFEST_BYTES + 1)
        after_fd = os.fstat(fp.fileno())
    after_path = path.lstat()
    if (len(data) > _MAX_MANIFEST_BYTES or
            _is_link(after_path) or
            (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
            != (after_fd.st_dev, after_fd.st_ino, after_fd.st_size, after_fd.st_mtime_ns) or
            (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
            != (after_path.st_dev, after_path.st_ino, after_path.st_size, after_path.st_mtime_ns)):
        raise ValueError("quality manifest changed during reading")
    try:
        document = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("invalid quality manifest JSON") from exc
    if not isinstance(document, dict) or set(document) != {
        "schema_version", "segments", "ledger_sha256",
    } or type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise ValueError("invalid quality manifest schema")
    entries = document["segments"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_QUALITY_SEGMENTS:
        raise ValueError("invalid quality manifest segment count")
    for i, entry in enumerate(entries, start=1):
        if (not isinstance(entry, dict) or set(entry) != {"sequence", "bytes", "sha256"}
                or type(entry["sequence"]) is not int or entry["sequence"] != i
                or type(entry["bytes"]) is not int or entry["bytes"] <= 0
                or not isinstance(entry["sha256"], str) or
                not _SHA.fullmatch(entry["sha256"])):
            raise ValueError("invalid quality manifest entry")
    if (not isinstance(document["ledger_sha256"], str) or
            not _SHA.fullmatch(document["ledger_sha256"]) or
            hashlib.sha256(_canonical(entries)).hexdigest() != document["ledger_sha256"]):
        raise ValueError("quality manifest ledger checksum mismatch")
    return document


def verify_quality_manifest(active: str | Path, archives: list[Path] | None = None) -> dict:
    """Verify *every* sealed archive; unsealed legacy history is explicit."""
    source = Path(active)
    if archives is None:
        archives = quality_stream_segments(source)
    before = _read_manifest(manifest_path(source))
    if before is None:
        return {
            "status": "unsealed_legacy" if archives else "not_applicable",
            "sealed_segments": 0,
        }
    expected = before["segments"]
    if len(archives) != len(expected):
        raise ValueError("quality archive count differs from sealed manifest")
    for i, segment in enumerate(archives, start=1):
        if segment_fingerprint(segment, i) != expected[i - 1]:
            raise ValueError("quality archive integrity checksum mismatch")
    # Re-read the ledger to reject a concurrent metadata replacement.
    if _read_manifest(manifest_path(source)) != before:
        raise ValueError("quality manifest changed during verification")
    return {"status": "verified", "sealed_segments": len(expected)}


def _publish_manifest(path: Path, entries: list[dict], *, replace: bool) -> None:
    """Write tmp/fsync/atomic replace. Any error before replace leaves old ledger."""
    if not replace and (path.exists() or path.is_symlink()):
        raise FileExistsError("quality manifest already exists")
    payload = (_canonical(_manifest_document(entries)) + b"\n")
    if len(payload) > _MAX_MANIFEST_BYTES:
        raise ValueError("quality manifest exceeds bounded metadata budget")
    tmp = path.with_name(path.name + ".tmp-" + uuid4().hex)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
    fd = os.open(tmp, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(payload)
            out.flush()
            os.fsync(out.fileno())
        if not replace and (path.exists() or path.is_symlink()):
            raise FileExistsError("quality manifest was created concurrently")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def advance_quality_manifest(active: Path, previous: list[Path], target: Path) -> None:
    """Run only while the existing per-run writer lock is held.

    The caller handles restoring the renamed source if publication fails.
    Do not silently initialize against old unsealed archives: initial sealing
    requires an operator's explicit trust-on-first-use acknowledgement.
    """
    path = manifest_path(active)
    existing = _read_manifest(path)
    if existing is None:
        if previous:
            return  # Legacy rotation stays unsealed; never imply verification.
        # First-ever rotation may establish a ledger without prior history.
        entries = [segment_fingerprint(target, 1)]
        _publish_manifest(path, entries, replace=False)
        return
    verify_quality_manifest(active, previous)
    entries = existing["segments"] + [segment_fingerprint(target, len(previous) + 1)]
    _publish_manifest(path, entries, replace=True)


def initialize_quality_manifest(audit_path: str | Path) -> dict:
    """Explicit trust-on-first-use sealing of prior unsealed numbered archives.

    All writers and GUI readers must be stopped. No archives are modified.
    """
    audit = Path(audit_path)
    if (audit.suffix.lower() != ".csv" or
            not audit.name.startswith("llm_call_audit_")):
        raise ValueError("expected canonical llm_call_audit_<run_id>.csv filename")
    source = quality_event_path(str(audit))
    if source is None or not source.parent.is_dir():
        raise FileNotFoundError("quality archive directory not found")
    for component in (source.parent, *source.parent.parents):
        if component.is_symlink():
            raise ValueError("quality manifest refuses symlink directories")
    lock = source.with_suffix(source.suffix + ".lock")
    if lock.is_symlink():
        raise ValueError("quality lock must not be a symlink")
    with lock.open("a+b") as fp:
        if fp.seek(0, os.SEEK_END) == 0:
            fp.write(b"0")
            fp.flush()
        _lock_stream(fp)
        try:
            if _read_manifest(manifest_path(source)) is not None:
                raise ValueError("quality archive already sealed; refusing rebaseline")
            archives = quality_stream_segments(source)
            if not archives:
                raise ValueError("no quality archived segments to initialize")
            entries = [segment_fingerprint(p, i) for i, p in enumerate(archives, start=1)]
            _publish_manifest(manifest_path(source), entries, replace=False)
            return {"status": "verified", "sealed_segments": len(entries)}
        finally:
            _unlock_stream(fp)
