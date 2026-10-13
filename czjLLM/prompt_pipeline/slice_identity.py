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
    """Hash decoded text with platform-independent line endings.

    Files written in text mode on Windows may contain CRLF, while the LLM
    returns LF strings. Normalize both sides before comparing identities.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


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
        output_hash = digest_text(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
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


def _write_child_prompt(path: Path, text: str) -> None:
    """Install one split child atomically after durable parent intent."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def install_split_prompts(
    prompt_file: str, prompt: str, children: list[tuple[str, str]],
) -> None:
    """Write split intent first, then both children; parent remains recoverable.

    Caller may unlink the original parent only after both atomic installs
    return. On a crash with the parent still queued, reconciliation discards
    partial descendants and safely retries the original.
    """
    file = Path(prompt_file)
    if file.parent.name not in {"TODO", "RUNNING"}:
        raise ValueError("split parent must be a queued prompt")
    record_split_identity(prompt_file, prompt, children)
    todo_dir = file.parent.parent / "TODO"
    for name, text in children:
        _write_child_prompt(todo_dir / name, text)


def _split_child_complete(
    root: Path, name: str, prompt_hash: str, visited: frozenset[str] = frozenset(),
) -> bool:
    """Check a queued, successful, or recursively split child without mutating.

    Committed nested retry splits replace their parent prompt. Reconciliation
    must therefore accept verified descendants instead of requiring the direct
    child basename in TODO, RUNNING, or Success.
    """
    if name in visited:
        raise RuntimeError("cyclic extract split lineage")
    if Path(name).name != name or not name.endswith(".txt"):
        raise RuntimeError("invalid extract split child name")
    visited = visited | {name}
    queued = [
        root / queue / name for queue in ("TODO", "RUNNING")
        if (root / queue / name).is_file()
    ]
    for path in queued:
        if digest_text(path.read_text(encoding="utf-8")) != prompt_hash:
            raise RuntimeError(
                "changed extract split child prompt; manual recovery required"
            )
    if queued or valid_success(str(root), name, prompt_hash):
        return True
    nested = _read_record(_record_path(root, "splits", name))
    if not nested:
        return False
    if (nested.get("version") != 1
            or nested.get("parent_prompt_sha256") != prompt_hash):
        raise RuntimeError("stale extract split descendant identity")
    children = nested.get("children")
    if not isinstance(children, list) or len(children) != 2:
        raise RuntimeError("invalid extract split descendant lineage")
    seen_children = set()
    for child in children:
        if not isinstance(child, dict):
            raise RuntimeError("invalid extract split descendant")
        child_name = child.get("name")
        child_hash = child.get("prompt_sha256")
        if (not isinstance(child_name, str)
                or not child_name.startswith(Path(name).stem + "-")
                or Path(child_name).name != child_name
                or not child_name.endswith(".txt")
                or not isinstance(child_hash, str) or len(child_hash) != 64
                or child_name in seen_children):
            raise RuntimeError("invalid extract split descendant identity")
        seen_children.add(child_name)
        if not _split_child_complete(root, child_name, child_hash, visited):
            return False
    return True


def _rollback_queued_descendants(
    root: Path, name: str, prompt_hash: str,
    visited: frozenset[str] = frozenset(),
) -> tuple[list[Path], list[Path]]:
    """Collect and validate every queued descendant before any rollback.

    The original parent remains recoverable. Remove nested descendants as
    well as direct children to prevent partial retry trees becoming roots.
    Successful output artifacts are never deleted.
    """
    if name in visited or Path(name).name != name or not name.endswith(".txt"):
        raise RuntimeError("invalid or cyclic extract split rollback")
    visited = visited | {name}
    queued: list[Path] = []
    intents: list[Path] = []
    for directory in ("TODO", "RUNNING"):
        file = root / directory / name
        if file.is_file():
            if digest_text(file.read_text(encoding="utf-8")) != prompt_hash:
                raise RuntimeError(
                    "changed extract split child prompt; manual recovery required"
                )
            queued.append(file)
    intent = _record_path(root, "splits", name)
    if intent.is_file():
        record = _read_record(intent)
        if (record.get("version") != 1
                or record.get("parent_prompt_sha256") != prompt_hash):
            raise RuntimeError("stale extract split rollback identity")
        children = record.get("children")
        if not isinstance(children, list) or len(children) != 2:
            raise RuntimeError("invalid extract split rollback lineage")
        child_names: set[str] = set()
        for child in children:
            if not isinstance(child, dict):
                raise RuntimeError("invalid extract split rollback child")
            cn, ch = child.get("name"), child.get("prompt_sha256")
            if (not isinstance(cn, str) or cn in child_names
                    or not cn.startswith(Path(name).stem + "-")
                    or Path(cn).name != cn or not cn.endswith(".txt")
                    or not isinstance(ch, str) or len(ch) != 64):
                raise RuntimeError("invalid extract split rollback child identity")
            child_names.add(cn)
            q, i = _rollback_queued_descendants(root, cn, ch, visited)
            queued.extend(q)
            intents.extend(i)
        intents.append(intent)
    return queued, intents


def reconcile_split_transitions(item: str) -> None:
    """Roll back interrupted parent→child installs before queue resume.

    Never leave both a recoverable parent and its partly/fully installed
    children as independent TODO roots. The intent record is installed first,
    so crashes at any child write or before parent unlink can be recovered.
    A missing parent with incomplete child set is an error, not a partial
    aggregate. No Success output or prompt content is deleted.
    """
    root = Path(item)
    directory = _identity_dir(root, "splits")
    if not directory.is_dir():
        return
    for intent in sorted(directory.glob("*.txt.json")):
        parent_name = intent.name[:-5]  # remove only the .json extension
        if _record_path(root, "splits", parent_name) != intent:
            raise RuntimeError("invalid extract split intent path")
        data = _read_record(intent)
        children = data.get("children")
        if (data.get("version") != 1 or not isinstance(children, list)
                or len(children) != 2):
            raise RuntimeError("invalid or incomplete extract split transition")
        names = []
        for child in children:
            if not isinstance(child, dict):
                raise RuntimeError("invalid extract split child metadata")
            name, digest = child.get("name"), child.get("prompt_sha256")
            if (not isinstance(name, str) or Path(name).name != name
                    or not name.startswith(Path(parent_name).stem + "-")
                    or not name.endswith(".txt") or not isinstance(digest, str)
                    or len(digest) != 64):
                raise RuntimeError("invalid extract split child identity")
            names.append((name, digest))
        if names[0][0] == names[1][0]:
            raise RuntimeError("duplicate extract split children")

        parent_exists = any((root / folder / parent_name).is_file()
                            for folder in ("TODO", "RUNNING"))
        installed = []
        for name, digest in names:
            queued = [root / folder / name for folder in ("TODO", "RUNNING")]
            seen = [p for p in queued if p.is_file()]
            for child_path in seen:
                if digest_text(child_path.read_text(encoding="utf-8")) != digest:
                    raise RuntimeError("changed extract split child prompt; manual recovery required")
            # A committed child may already have split into grandchildren.
            # Inspect hash-bound descendant lineage without creating roots.
            complete = _split_child_complete(root, name, digest)
            installed.append((seen, complete))
        if parent_exists:
            # Validate the *entire* queued descendant tree before deletion.
            # A child may have committed a nested split before its ancestor
            # parent was recovered. Keeping grandchildren as fresh roots
            # would otherwise duplicate the original source.
            queued_descendants: list[Path] = []
            nested_intents: list[Path] = []
            for name, digest in names:
                queued, intents = _rollback_queued_descendants(root, name, digest)
                queued_descendants.extend(queued)
                nested_intents.extend(intents)
            # Delete descendants deepest-first and the parent intent LAST;
            # if recovery crashes, the original queued parent remains.
            for file in queued_descendants:
                file.unlink(missing_ok=True)
            for nested in nested_intents:
                nested.unlink(missing_ok=True)
            intent.unlink()
        elif not all(complete for _, complete in installed):
            # Even when BOTH children are missing (e.g. filesystem loss), the
            # durable intent proves that this parent once had input content.
            # Silently accepting zero descendants allows partial writeback.
            raise RuntimeError(
                "extract split transition incomplete without recoverable parent"
            )


def include_committed_split_roots(
    item: str, current: dict[str, str],
) -> dict[str, str]:
    """Restore a verified committed split's original root into coverage.

    Current TODO/RUNNING contains only unfinished descendants. A sibling
    already moved to Success must still be included, but stale Success alone
    cannot establish current membership. Anchor each committed split to at
    least one *current queued* descendant and verify its two child branches.
    Collapse nested splits deepest-first so the outer root covers the entire
    lineage without double-counting descendants.
    """
    root = Path(item)
    intents = _identity_dir(root, "splits")
    if not intents.is_dir() or not current:
        return dict(current)
    expected = dict(current)
    for path in sorted(
        intents.glob("*.txt.json"),
        key=lambda p: (-p.name[:-9].count("-"), p.name),
    ):
        parent = path.name[:-5]
        # A queued parent is still the source of truth, so ignore its
        # uncommitted child tree (reconciliation should clear that intent).
        if any((root / folder / parent).is_file() for folder in ("TODO", "RUNNING")):
            continue
        record = _read_record(path)
        if record.get("version") != 1:
            raise RuntimeError("invalid committed extract split identity")
        parent_hash = record.get("parent_prompt_sha256")
        children = record.get("children")
        if (not isinstance(parent_hash, str) or len(parent_hash) != 64
                or not isinstance(children, list) or len(children) != 2):
            raise RuntimeError("invalid committed extract split lineage")
        child_pairs = []
        for child in children:
            if not isinstance(child, dict):
                raise RuntimeError("invalid committed extract split child")
            name, child_hash = child.get("name"), child.get("prompt_sha256")
            if (not isinstance(name, str) or not name.startswith(Path(parent).stem + "-")
                    or Path(name).name != name or not name.endswith(".txt")
                    or not isinstance(child_hash, str) or len(child_hash) != 64):
                raise RuntimeError("invalid committed extract split child")
            child_pairs.append((name, child_hash))
        if child_pairs[0][0] == child_pairs[1][0]:
            raise RuntimeError("duplicate committed extract split children")
        # Only a queue descendant anchors a lineage to this current work.
        # It may already have been collapsed to an intermediate split root.
        descendants = [
            key for key in expected
            if any(key == name or key.startswith(Path(name).stem + "-")
                   for name, _ in child_pairs)
        ]
        if not descendants:
            continue
        for name, child_hash in child_pairs:
            if not _split_child_complete(root, name, child_hash):
                raise RuntimeError("incomplete committed extract split branch")
        for key in descendants:
            expected.pop(key)
        if parent in expected:
            raise RuntimeError("overlapping committed extract split roots")
        expected[parent] = parent_hash
    return dict(sorted(expected.items()))


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
