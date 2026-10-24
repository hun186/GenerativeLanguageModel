"""Opt-in, loss-averse maintenance rotation for per-run quality JSONL.

Rotation is NEVER automatic and NEVER deletes an archive. Operators must stop
producers before rotation; the existing cross-process append lock serializes
cooperating writers during the atomic rename. Missing sequence numbers fail
closed instead of being silently omitted from offline diagnostics.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat

from czjLLM.utilities.processing_quality import (
    _lock_stream, _unlock_stream, quality_event_path,
)

MAX_QUALITY_SEGMENTS = 64
_SEGMENT_RE = re.compile(r"\.seg-([0-9]{8})\Z")


def quality_stream_segments(
    active: str | Path, *, max_segments: int = MAX_QUALITY_SEGMENTS,
) -> list[Path]:
    """List the canonical consecutive archived generations for one run.

    A missing or noncanonical numbered shard is not silently incorporated as
    a partial successful history. The active stream itself is never an archive.
    """
    if type(max_segments) is not int or not 1 <= max_segments <= MAX_QUALITY_SEGMENTS:
        raise ValueError("invalid quality segment bound")
    source = Path(active)
    files = []
    for candidate in source.parent.glob(source.name + ".seg-*"):
        suffix = candidate.name[len(source.name):]
        match = _SEGMENT_RE.fullmatch(suffix)
        if match is None:
            raise ValueError("noncanonical quality segment name")
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError("quality segments must be regular non-symlink files")
        files.append((int(match.group(1)), candidate))
        if len(files) > max_segments:
            raise ValueError("quality stream exceeds segment budget")
    files.sort(key=lambda item: item[0])
    if [seq for seq, _ in files] != list(range(1, len(files) + 1)):
        raise ValueError("quality stream has missing or invalid segment sequence")
    return [path for _, path in files]


def rotate_quality_event_stream(
    audit_path: str | Path, *, max_segments: int = MAX_QUALITY_SEGMENTS,
) -> dict:
    """Manually rename a complete active run JSONL to a numbered immutable shard.

    Does not create or modify any event, truncate the log or delete archives.
    A producer's next emit recreates the same stable active filename. The user
    must stop producer/GUI processes for maintenance: cross-process locks
    serialize cooperating writers but not uncooperative external editors.
    """
    audit = Path(audit_path)
    if (audit.suffix.lower() != ".csv"
            or not audit.name.startswith("llm_call_audit_")):
        raise ValueError("expected canonical llm_call_audit_<run_id>.csv filename")
    source = quality_event_path(str(audit))
    if source is None:
        raise ValueError("missing quality audit path")
    if type(max_segments) is not int or not 1 <= max_segments <= MAX_QUALITY_SEGMENTS:
        raise ValueError("invalid quality segment bound")
    lock_path = source.with_suffix(source.suffix + ".lock")
    for component in (source.parent, *source.parent.parents, lock_path):
        if component.is_symlink():
            raise ValueError("quality rotation refuses symlink path components")
    source.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_fp:
        if lock_fp.seek(0, os.SEEK_END) == 0:
            lock_fp.write(b"0")
            lock_fp.flush()
        _lock_stream(lock_fp)
        try:
            archives = quality_stream_segments(source, max_segments=max_segments)
            if source.is_symlink():
                raise ValueError("quality active stream must not be a symlink")
            if not source.exists():
                raise FileNotFoundError("active quality stream not found")
            metadata = source.stat()
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("active quality stream must be a regular file")
            if metadata.st_size == 0:
                return {"rotated": False, "archived_segments": len(archives)}
            with source.open("rb") as fp:
                fp.seek(-1, os.SEEK_END)
                if fp.read(1) != b"\n":
                    raise ValueError("active quality stream has an incomplete final record")
            if len(archives) >= max_segments:
                raise ValueError("quality stream archive segment budget reached")
            target = source.with_name(f"{source.name}.seg-{len(archives) + 1:08d}")
            if target.exists() or target.is_symlink():
                raise FileExistsError("quality segment destination already exists")
            # Atomic same-directory move. No destructive truncation/copy/rewrite.
            os.rename(source, target)
            return {"rotated": True, "archived_segments": len(archives) + 1}
        finally:
            _unlock_stream(lock_fp)
