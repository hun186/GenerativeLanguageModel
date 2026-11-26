"""In-memory, one-shot source provenance for fresh legacy Queue files.

The trusted Producer supplies the envelope; never reconstruct it from disk.
The current task fingerprint and actual claimed inode are independently
checked by the Consumer. A missing receipt is a normal fail-closed outcome.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
from uuid import uuid4

from czjLLM.prompt_pipeline.task_fingerprint import fingerprint_task
from czjLLM.prompt_pipeline.runtime_support.queue_observation import verified_claim_observation
from czjLLM.utilities.json_rule_handoff import encode_source_handoff, decode_source_handoff
from czjLLM.utilities.json_rule_policy import parse_json_repair_policy
from czjLLM.utilities.json_rule_repair import MAX_CHARS

MAX_SOURCE_RECEIPTS_PER_ITEM = 1024


def source_task_fingerprint(task, renderer_pool) -> str:
    try:
        if not isinstance(task, str):
            return ""
        spec = renderer_pool.get(task)
        if not parse_json_repair_policy(spec).multidim_evidence_quotes:
            return ""
        return fingerprint_task({"task": task, "spec": spec})
    except Exception:
        return ""


def _identity(info):
    if not stat.S_ISREG(info.st_mode) or info.st_ino <= 0 or info.st_nlink != 1:
        return None
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _safe_path(path):
    return not any(p.is_symlink() for p in (path, *path.parents))


@dataclass(frozen=True)
class GeneratedSourceHandoff:
    generation_id: str
    file_identity: tuple
    wire: str


def generated_source_handoff(path, stream, prompt, receipt, task_sha256):
    """Called only for a newly created exclusive TODO file, never overwrite."""
    try:
        path = Path(path)
        if path.parent.name != "TODO" or path.suffix != ".txt" or not _safe_path(path):
            return None
        stream.flush()
        opened = _identity(os.fstat(stream.fileno()))
        current = _identity(path.lstat())
        if opened is None or opened != current:
            return None
        generation = uuid4().hex
        wire = encode_source_handoff(
            prompt, receipt, generation_id=generation, task_sha256=task_sha256,
        )
        return GeneratedSourceHandoff(generation, opened, wire) if wire is not None else None
    except (OSError, ValueError, TypeError, UnicodeError):
        return None


def finalize_generated_source_handoff(record, path):
    """NTFS may finalize mtime only after the writer closes.

    Accept the post-close identity only for the same exclusive inode and
    byte length. Consumer still verifies the exact decoded prompt and claim.
    """
    if not isinstance(record, GeneratedSourceHandoff):
        return None
    try:
        path = Path(path)
        if not _safe_path(path):
            return None
        current = _identity(path.lstat())
        if current is None or current[:3] != record.file_identity[:3]:
            return None
        return GeneratedSourceHandoff(record.generation_id, current, record.wire)
    except (OSError, ValueError, TypeError):
        return None


def claimed_source_receipt(record, path, claim_id, task_sha256):
    """One-shot Consumer verification; no persistence and no search by digest."""
    if not isinstance(record, GeneratedSourceHandoff) or not task_sha256:
        return None
    try:
        path = Path(path)
        if path.parent.name != "RUNNING" or path.suffix != ".txt" or not _safe_path(path):
            return None
        if _identity(path.lstat()) != record.file_identity:
            return None
        if not verified_claim_observation(path, claim_id):
            return None
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        with os.fdopen(os.open(path, flags), "r", encoding="utf-8", newline=None) as stream:
            if _identity(os.fstat(stream.fileno())) != record.file_identity:
                return None
            prompt = stream.read(MAX_CHARS + 1)
            if _identity(os.fstat(stream.fileno())) != record.file_identity:
                return None
        if len(prompt) > MAX_CHARS or _identity(path.lstat()) != record.file_identity:
            return None
        return decode_source_handoff(
            record.wire, prompt, expected_generation_id=record.generation_id,
            expected_task_sha256=task_sha256,
        )
    except (OSError, ValueError, TypeError, UnicodeError):
        return None


def take_claimed_source_receipt(registry, item_dir, prompt_file, claim_id, task, renderer_pool):
    """Take only from this run's registered row, not a path/hash search."""
    try:
        path = Path(prompt_file)
        if path.parent.parent != Path(item_dir) or path.parent.name != "RUNNING":
            return None
        take = getattr(registry, "take_claimed_source_handoff", None)
        if not callable(take):
            return None
        record = take(item_dir, path.name, claim_id)
        if record is None:
            return None
        return claimed_source_receipt(
            record, path, claim_id, source_task_fingerprint(task, renderer_pool),
        )
    except Exception:
        return None
