"""Read-only, bounded inventory of pre-L3 Reduction filesystem artifacts.

Shares the L3 GC discovery boundary, but never validates ownership for
adoption, invokes retention deletion, creates leases, or reads payloads.
"""

from __future__ import annotations

import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from czjLLM.reduction.retention import (
    DEFAULT_SCAN_LIMIT,
    MARKER_NAME,
    ReductionArtifactKind,
    RetentionRoot,
    RetentionRootKind,
    _contained_child,
    _discover,
    _is_reparse_path,
    _is_reduction_metadata_name,
    item_retention_root,
)


_CHECKPOINT_ID = re.compile(r"[0-9a-f]{64}\Z")
_RUNTIME_ID = re.compile(r"round-[0-9]{4,}\Z")


@dataclass(frozen=True)
class LegacyArtifactInventory:
    """Aggregate-only report; never disclose paths, IDs, or file contents."""

    report_version: int = 1
    read_only: bool = True
    scanned_entries: int = 0
    candidate_directories: int = 0
    marker_files_present_unverified: int = 0
    marker_nonregular: int = 0
    unmarked_checkpoint_manifest_present_unverified: int = 0
    unmarked_checkpoint_manifest_missing: int = 0
    unmarked_checkpoint_manifest_nonregular: int = 0
    unmarked_runtime_rounds: int = 0
    unrecognized_unmarked_directories: int = 0
    skipped_containment: int = 0
    scan_limit_reached: bool = False


def _file_type(path: Path) -> int | None:
    """No symlink following or file reads; fail closed on unexpected errors."""
    try:
        return path.lstat().st_mode
    except FileNotFoundError:
        return None


def inventory_legacy_reduction_artifacts(
    roots: Iterable[str | Path | RetentionRoot],
    *,
    max_scan_entries: int = DEFAULT_SCAN_LIMIT,
) -> LegacyArtifactInventory:
    """Inspect approved L3 item/prompt roots with no filesystem writes.

    A checkpoint with a regular run.json is NOT validated or migration
    eligible; it could be active, corrupt, stale or incompatible.
    """
    if type(max_scan_entries) is not int or max_scan_entries <= 0:
        raise ValueError("max_scan_entries must be a positive integer")

    unique_roots: dict[tuple[RetentionRootKind, Path], RetentionRoot] = {}
    for supplied in roots:
        root = supplied if isinstance(supplied, RetentionRoot) else item_retention_root(supplied)
        if root.kind not in (RetentionRootKind.ITEM, RetentionRootKind.PROMPT_CONTAINER):
            raise ValueError("unsupported inventory root kind")
        if not root.path.is_dir():
            raise ValueError("inventory root must be an existing directory")
        # Check every supplied path component BEFORE canonicalizing: Windows
        # junctions and intermediate symlinks must never widen approval scope.
        absolute = root.path.absolute()
        if any(_is_reparse_path(part) for part in (absolute, *absolute.parents)):
            raise ValueError("symlink or junction inventory roots are not accepted")
        canonical = root.path.resolve(strict=True)
        reserved_parts = [i for i, part in enumerate(canonical.parts)
                          if _is_reduction_metadata_name(part)]
        if root.kind is RetentionRootKind.PROMPT_CONTAINER and reserved_parts:
            raise ValueError("prompt root cannot be within a .reduction metadata directory")
        if root.kind is RetentionRootKind.ITEM and reserved_parts:
            if reserved_parts != [len(canonical.parts) - 1]:
                raise ValueError("item root cannot be nested within a .reduction metadata directory")
            # L3 _discover accepts either the workspace or its .reduction
            # directory; they must share one budget/identity in the inventory.
            canonical = canonical.parent
        unique_roots[(root.kind, canonical)] = RetentionRoot(canonical, root.kind)
    if not unique_roots:
        raise ValueError("at least one approved inventory root is required")

    prompt_roots = {path for kind, path in unique_roots if kind is RetentionRootKind.PROMPT_CONTAINER}
    approved = []
    for (kind, path), root in unique_roots.items():
        if kind is RetentionRootKind.ITEM and (
            path.parent in prompt_roots
        ):
            # Prompt traversal already covers this immediate item; do not
            # exhaust the scan budget visiting the same child a second time.
            continue
        approved.append(root)

    candidates, truncated, scanned = _discover(approved, max_scan_entries)
    counts = {
        "marker_files_present_unverified": 0,
        "marker_nonregular": 0,
        "unmarked_checkpoint_manifest_present_unverified": 0,
        "unmarked_checkpoint_manifest_missing": 0,
        "unmarked_checkpoint_manifest_nonregular": 0,
        "unmarked_runtime_rounds": 0,
        "unrecognized_unmarked_directories": 0,
        "skipped_containment": 0,
    }
    unique_paths: set[Path] = set()
    for path, parent, kind in candidates:
        if not _contained_child(path, parent):
            counts["skipped_containment"] += 1
            continue
        # Overlapping item and Prompt scopes should not inflate audit counts.
        resolved = path.resolve(strict=True)
        if resolved in unique_paths:
            continue
        unique_paths.add(resolved)
        marker_mode = _file_type(path / MARKER_NAME)
        if marker_mode is not None:
            key = ("marker_files_present_unverified"
                   if stat.S_ISREG(marker_mode) else "marker_nonregular")
            counts[key] += 1
            continue

        if kind is ReductionArtifactKind.CHECKPOINT_RUN and _CHECKPOINT_ID.fullmatch(path.name):
            manifest_mode = _file_type(path / "run.json")
            key = ("unmarked_checkpoint_manifest_missing" if manifest_mode is None
                   else "unmarked_checkpoint_manifest_present_unverified"
                   if stat.S_ISREG(manifest_mode)
                   else "unmarked_checkpoint_manifest_nonregular")
            counts[key] += 1
        elif kind is ReductionArtifactKind.RUNTIME_ROUND and _RUNTIME_ID.fullmatch(path.name):
            counts["unmarked_runtime_rounds"] += 1
        else:
            counts["unrecognized_unmarked_directories"] += 1

    return LegacyArtifactInventory(
        scanned_entries=scanned,
        candidate_directories=len(unique_paths) + counts["skipped_containment"],
        scan_limit_reached=truncated,
        **counts,
    )
