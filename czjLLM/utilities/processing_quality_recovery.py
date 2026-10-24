"""Conservative opt-in rollback of an interrupted *sealed* JSONL rotation.

A crash after renaming the active JSONL but before publishing the advanced
archive ledger can leave one extra numbered archive. This module never
silently extends or rebaselines the ledger. It may restore that *one* extra
archive to the unsealed active path only with stopped-producer confirmation.

No evidence permits automatic recovery of missing/corrupt already sealed
segments, two extra shards, or a collision with a live active file.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat

from czjLLM.utilities.processing_quality import (
    _lock_stream, _unlock_stream, quality_event_path,
)
from czjLLM.utilities.processing_quality_manifest import (
    _read_manifest, manifest_path, segment_fingerprint,
    verify_quality_manifest,
)
from czjLLM.utilities.processing_quality_rotation import quality_stream_segments

_CANONICAL_AUDIT = re.compile(
    r"llm_call_audit_[A-Za-z0-9][A-Za-z0-9_.-]{0,100}\.csv\Z"
)


def _paths(audit_path: str | Path) -> tuple[Path, Path]:
    audit = Path(audit_path)
    if not _CANONICAL_AUDIT.fullmatch(audit.name):
        raise ValueError("invalid per-run quality audit filename")
    active = quality_event_path(str(audit))
    if active is None or not active.parent.is_dir():
        raise FileNotFoundError("quality audit directory is missing")
    for parent in (active.parent, *active.parent.parents):
        if parent.is_symlink():
            raise ValueError("quality audit directory symlink not allowed")
    lock_path = active.with_suffix(active.suffix + ".lock")
    if lock_path.is_symlink():
        raise ValueError("quality writer lock symlink not allowed")
    return active, lock_path


def _active_present(active: Path) -> bool:
    if active.is_symlink():
        raise ValueError("active quality file symlink not allowed")
    if not active.exists():
        return False
    if not stat.S_ISREG(active.stat().st_mode):
        raise ValueError("active quality stream must be regular")
    return True


def inspect_interrupted_rotation(audit_path: str | Path) -> dict:
    """Read-only state assessment; unverified states never return 'ready'."""
    active, _ = _paths(audit_path)
    archived = quality_stream_segments(active)
    ledger = _read_manifest(manifest_path(active))
    active_present = _active_present(active)

    if ledger is None:
        return {
            "status": "unsealed_legacy" if archived else "not_applicable",
            "sealed_segments": 0,
            "archived_segments": len(archived),
            "active_present": active_present,
        }

    sealed = ledger["segments"]
    if len(archived) == len(sealed):
        verify_quality_manifest(active, archived)
        status = "verified"
    elif len(archived) == len(sealed) + 1:
        # The extra shard is not covered by the signed? NO: this is an
        # unsigned local consistency ledger, and its origin is unproven.
        # It can be restored only to active, never auto-added as trusted.
        for index, segment in enumerate(archived[:len(sealed)], start=1):
            if segment_fingerprint(segment, index) != sealed[index - 1]:
                raise ValueError("sealed quality archive mismatch")
        segment_fingerprint(archived[-1], len(archived))
        if _read_manifest(manifest_path(active)) != ledger:
            raise ValueError("quality manifest changed during recovery inspection")
        status = "ambiguous_active_present" if active_present else "rollback_candidate"
    else:
        raise ValueError("sealed quality archive count does not admit safe rollback")

    return {
        "status": status,
        "sealed_segments": len(sealed),
        "archived_segments": len(archived),
        "active_present": active_present,
    }


def rollback_interrupted_rotation(audit_path: str | Path) -> dict:
    """Manually restore exactly one unsealed extra shard to inactive active path.

    Caller must stop *all* cooperating writers and external GUI readers.
    Like the existing manual rotation, this relies on that operator barrier:
    the lock cannot exclude unrelated noncooperating filesystem editors.
    """
    active, lock_path = _paths(audit_path)
    with lock_path.open("a+b") as fp:
        if fp.seek(0, os.SEEK_END) == 0:
            fp.write(b"0")
            fp.flush()
        _lock_stream(fp)
        try:
            inspection = inspect_interrupted_rotation(audit_path)
            if inspection["status"] != "rollback_candidate":
                raise ValueError("quality rotation rollback is not unambiguously eligible")
            archived = quality_stream_segments(active)
            candidate = archived[-1]
            before = segment_fingerprint(candidate, len(archived))
            # This is a stopped-producer maintenance operation, not a live
            # reader/writer online rename. Refuse any existing active file.
            if active.exists() or active.is_symlink():
                raise ValueError("quality active path collision")
            os.rename(candidate, active)
            # In the stopped environment, make sure bytes survived the rename
            # and the prior sealed archive set still agrees with its manifest.
            if segment_fingerprint(active, len(archived)) != before:
                raise ValueError("restored active quality bytes changed")
            verify_quality_manifest(active, archived[:-1])
            return {
                "status": "rolled_back_to_active_unsealed",
                "sealed_segments": len(archived) - 1,
                "restored_active": True,
            }
        finally:
            _unlock_stream(fp)
