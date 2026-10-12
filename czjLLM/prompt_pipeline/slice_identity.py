"""Hash-only provenance for safe single-extract JSON slice resume/writeback.

Metadata lives outside TODO/RUNNING/Success, contains no prompt or LLM output,
and is never a replacement for authoritative Success files. Missing or stale
metadata is a cache miss: a slice must rerun (or fail closed at writeback).
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path


def digest_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _identity_dir(item: Path, kind: str) -> Path:
    return item / "_extract_slice_identity" / kind


def _record_path(item: Path, kind: str, filename: str) -> Path:
    if Path(filename).name != filename or not filename.endswith(".txt"):
        raise ValueError("invalid slice filename")
    return _identity_dir(item, kind) / (filename + ".json")


def _atomic_record(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, sort_keys=True, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _read_record(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return {}
    return data if isinstance(data, dict) else {}


def record_success_identity(prompt_file: str, output_file: str, prompt: str, output: str) -> None:
    """Bind an actual successful output to its exact sent prompt and output."""
    dest = Path(output_file)
    if dest.parent.name != "Success":
        return
    _atomic_record(
        _record_path(dest.parent.parent, "success", dest.name),
        {"version": 1, "prompt_sha256": digest_text(prompt),
         "output_sha256": digest_text(output)},
    )


def valid_success(item: str, filename: str, prompt_hash: str) -> bool:
    root = Path(item)
    record = _read_record(_record_path(root, "success", filename))
    if record.get("version") != 1 or record.get("prompt_sha256") != prompt_hash:
        return False
    path = root / "Success" / filename
    try:
        output_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return False
    return record.get("output_sha256") == output_hash


def record_split_identity(
    prompt_file: str, prompt: str, children: list[tuple[str, str]],
) -> None:
    """Remember a failed parent's exact two replacement prompts."""
    file = Path(prompt_file)
    if file.parent.name not in {"RUNNING", "TODO"}:
        return
    if len(children) != 2:
        raise ValueError("split must have exactly two children")
    stem = file.stem + "-"
    if any(not name.startswith(stem) or not name.endswith(".txt") for name, _ in children):
        raise ValueError("split children do not belong to parent")
    _atomic_record(
        _record_path(file.parent.parent, "splits", file.name),
        {"version": 1, "parent_prompt_sha256": digest_text(prompt),
         "children": [{"name": name, "prompt_sha256": digest_text(value)}
                      for name, value in children]},
    )


def resolve_success_leaves(
    item: str, filename: str, prompt_hash: str, visited: set[str] | None = None,
) -> list[str]:
    """Require a success or two recursively verified replacement descendants."""
    seen = visited if visited is not None else set()
    if filename in seen:
        raise ValueError("cyclic or duplicate extract split lineage")
    seen.add(filename)
    if valid_success(item, filename, prompt_hash):
        return [filename]
    split = _read_record(_record_path(Path(item), "splits", filename))
    if split.get("version") != 1 or split.get("parent_prompt_sha256") != prompt_hash:
        raise ValueError("missing or stale extract Success prompt identity")
    children = split.get("children")
    if not isinstance(children, list) or len(children) != 2:
        raise ValueError("incomplete extract split lineage")
    leaves = []
    for child in children:
        if not isinstance(child, dict):
            raise ValueError("invalid extract split lineage")
        name, hash_value = child.get("name"), child.get("prompt_sha256")
        if (not isinstance(name, str) or not name.startswith(Path(filename).stem + "-")
                or not name.endswith(".txt") or Path(name).name != name
                or not isinstance(hash_value, str) or len(hash_value) != 64):
            raise ValueError("invalid extract split child")
        leaves.extend(resolve_success_leaves(item, name, hash_value, seen))
    return leaves
