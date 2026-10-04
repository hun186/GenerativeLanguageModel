"""Opt-in, ownership-based retention for Reduction filesystem artifacts.

This module deliberately owns only L3 checkpoint runs and transient text-round
directories.  Legacy artifacts and persisted source/sink results are not
discoverable through this API.
"""

from __future__ import annotations

import json
import math
import os
import re
import secrets
import shutil
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping

from czjLLM.reduction.artifacts import CHECKPOINT_CONTRACT_VERSION, CheckpointStore
from czjLLM.utilities.atomic_io import atomic_write_json


OWNER = "czjLLM.reduction"
MARKER_NAME = ".retention.json"
LEASE_NAME = ".execution-lease"
GC_CLAIM_NAME = ".gc-claim"
LEASE_RECLAIM_NAME = ".lease-reclaim"
TOMBSTONE_MARKER = ".gc-tombstone.json"
RETENTION_SCHEMA_VERSION = 1
DEFAULT_LEASE_DURATION = timedelta(hours=6)
DEFAULT_SCAN_LIMIT = 10_000


class ReductionArtifactKind(str, Enum):
    CHECKPOINT_RUN = "checkpoint_run"
    RUNTIME_ROUND = "runtime_round"


class RetentionRootKind(str, Enum):
    ITEM = "item"
    PROMPT_CONTAINER = "prompt_container"


@dataclass(frozen=True)
class RetentionRoot:
    path: Path
    kind: RetentionRootKind = RetentionRootKind.ITEM


def item_retention_root(path: str | Path) -> RetentionRoot:
    return RetentionRoot(Path(path), RetentionRootKind.ITEM)


def prompt_container_retention_root(path: str | Path) -> RetentionRoot:
    """Approve only immediate, non-symlink item children of a prompt root."""
    return RetentionRoot(Path(path), RetentionRootKind.PROMPT_CONTAINER)


@dataclass(frozen=True)
class ReductionRetentionPolicy:
    enabled: bool = False
    dry_run: bool = False
    checkpoint_terminal_ttl_days: float = 14
    checkpoint_incomplete_ttl_days: float = 30
    transient_runtime_ttl_hours: float = 24
    cleanup_transient_on_success: bool = True
    max_delete_entries_per_sweep: int = 100
    max_delete_bytes_per_sweep: int = 1024 * 1024 * 1024
    max_scan_entries_per_sweep: int = DEFAULT_SCAN_LIMIT


@dataclass(frozen=True)
class RetentionCandidate:
    artifact_id: str
    kind: ReductionArtifactKind
    terminal: bool
    age_seconds: float
    reclaimable_bytes: int


@dataclass(frozen=True)
class RetentionReport:
    scanned: int = 0
    owned: int = 0
    eligible: int = 0
    deleted: int = 0
    bytes_reclaimed: int = 0
    skipped_active: int = 0
    skipped_young: int = 0
    skipped_unowned: int = 0
    skipped_invalid: int = 0
    errors: int = 0
    budget_exhausted: bool = False
    scan_limit_reached: bool = False
    dry_run: bool = False

    def safe_summary(self) -> Mapping[str, int | bool]:
        return MappingProxyType(dict(self.__dict__))


_POLICY_KEYS = frozenset(ReductionRetentionPolicy.__dataclass_fields__)


def parse_reduction_retention_policy(value: Any) -> ReductionRetentionPolicy:
    if value is None:
        return ReductionRetentionPolicy()
    if isinstance(value, ReductionRetentionPolicy):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("reduction_retention must be a mapping")
    unknown = set(value) - _POLICY_KEYS
    if unknown:
        raise ValueError(f"unknown reduction_retention keys: {sorted(unknown)!r}")
    bool_keys = {"enabled", "dry_run", "cleanup_transient_on_success"}
    ttl_keys = {
        "checkpoint_terminal_ttl_days", "checkpoint_incomplete_ttl_days",
        "transient_runtime_ttl_hours",
    }
    int_keys = {
        "max_delete_entries_per_sweep", "max_delete_bytes_per_sweep",
        "max_scan_entries_per_sweep",
    }
    data = dict(value)
    for key in bool_keys & data.keys():
        if type(data[key]) is not bool:
            raise TypeError(f"{key} must be bool")
    for key in ttl_keys & data.keys():
        item = data[key]
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise TypeError(f"{key} must be a finite number")
        if not math.isfinite(float(item)) or item < 0:
            raise ValueError(f"{key} must be finite and >= 0")
        data[key] = float(item)
    for key in int_keys & data.keys():
        if type(data[key]) is not int or data[key] <= 0:
            raise ValueError(f"{key} must be a positive integer")
    policy = ReductionRetentionPolicy(**data)
    if policy.checkpoint_incomplete_ttl_days < policy.checkpoint_terminal_ttl_days:
        raise ValueError("checkpoint incomplete TTL must be >= terminal TTL")
    return policy


def project_reduction_retention_policy(ctx: Any, get_param: Callable[[str, Any], Any]) -> ReductionRetentionPolicy:
    """Project and validate root YAML operational policy before scheduling."""
    policy = parse_reduction_retention_policy(get_param("reduction_retention", None))
    ctx.reduction_retention = policy
    return policy


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("retention clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("timestamp must be strict UTC")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.tzinfo != timezone.utc:
        raise ValueError("timestamp must be UTC")
    return parsed


def write_artifact_marker(
    artifact_dir: str | Path, *, kind: ReductionArtifactKind, artifact_id: str,
    now: Callable[[], datetime] = _utc_now,
) -> None:
    """Create or touch bounded operational ownership metadata atomically."""
    path = Path(artifact_dir)
    path.mkdir(parents=True, exist_ok=True)
    marker = path / MARKER_NAME
    created = _timestamp(now())
    if marker.is_file() and not marker.is_symlink():
        try:
            prior = json.loads(marker.read_text(encoding="utf-8"))
            if (prior.get("schema_version"), prior.get("owner"), prior.get("kind"),
                    prior.get("artifact_id")) == (
                    RETENTION_SCHEMA_VERSION, OWNER, kind.value, artifact_id):
                created = prior["created_at"]
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            pass
    stamp = _timestamp(now())
    atomic_write_json(str(marker), {
        "schema_version": RETENTION_SCHEMA_VERSION, "owner": OWNER,
        "kind": kind.value, "created_at": created, "last_touched_at": stamp,
        "artifact_id": artifact_id,
    })


class ArtifactLease:
    """Cross-process mkdir lease; execution and GC claims mutually re-check."""

    def __init__(self, artifact_dir: str | Path, *, now: Callable[[], datetime] = _utc_now,
                 duration: timedelta = DEFAULT_LEASE_DURATION) -> None:
        self.artifact_dir = Path(artifact_dir)
        self.now = now
        self.duration = duration
        self.path = self.artifact_dir / LEASE_NAME
        self.token = secrets.token_hex(16)
        self.acquired = False

    def acquire(self) -> "ArtifactLease":
        if ((self.artifact_dir / GC_CLAIM_NAME).exists()
                or (self.artifact_dir / LEASE_RECLAIM_NAME).exists()):
            raise RuntimeError("artifact is claimed by retention GC")
        try:
            self.path.mkdir()
        except FileExistsError:
            reclaim = self.artifact_dir / LEASE_RECLAIM_NAME
            try:
                reclaim.mkdir()
            except FileExistsError:
                raise RuntimeError("artifact already has an active execution lease")
            stale = self.artifact_dir / f".stale-lease-{secrets.token_hex(8)}"
            try:
                if _lease_is_active(self.artifact_dir, self.now()):
                    raise RuntimeError("artifact already has an active execution lease")
                self.path.rename(stale)
                self.path.mkdir()
                shutil.rmtree(stale)
            finally:
                shutil.rmtree(reclaim, ignore_errors=True)
        self.acquired = True
        self.refresh()
        if ((self.artifact_dir / GC_CLAIM_NAME).exists()
                or (self.artifact_dir / LEASE_RECLAIM_NAME).exists()):
            self.release()
            raise RuntimeError("artifact was claimed by retention GC")
        return self

    def refresh(self) -> None:
        if not self.acquired:
            return
        atomic_write_json(str(self.path / "lease.json"), {
            "schema_version": 1, "owner": OWNER, "token": self.token,
            "expires_at": _timestamp(self.now() + self.duration),
        })

    def release(self) -> None:
        if not self.acquired:
            return
        try:
            data = _read_json(self.path / "lease.json")
            if data.get("token") == self.token:
                shutil.rmtree(self.path)
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        self.acquired = False

    def __enter__(self) -> "ArtifactLease":
        return self.acquire()

    def __exit__(self, *_args: Any) -> None:
        self.release()


def _read_json(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("metadata is not an object")
    return value


def _lease_is_active(path: Path, now: datetime) -> bool:
    lease = path / LEASE_NAME
    if not lease.is_dir() or lease.is_symlink():
        return False
    try:
        data = _read_json(lease / "lease.json")
        return data.get("owner") == OWNER and _parse_timestamp(data.get("expires_at")) > now
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def _contained_child(path: Path, approved_parent: Path) -> bool:
    if path.is_symlink() or approved_parent.is_symlink():
        return False
    try:
        resolved = path.resolve(strict=True)
        parent = approved_parent.resolve(strict=True)
        return resolved != parent and resolved.parent == parent
    except (OSError, RuntimeError):
        return False


def _tree_size(path: Path) -> int:
    total = 0
    stack = [path]
    while stack:
        current = stack.pop()
        for entry in os.scandir(current):
            stat = entry.stat(follow_symlinks=False)
            total += stat.st_size
            if entry.is_dir(follow_symlinks=False):
                stack.append(Path(entry.path))
    return total


def _validate_marker(
    path: Path, kind: ReductionArtifactKind, *, expected_artifact_id: str | None = None,
) -> Mapping[str, Any]:
    marker_path = path / MARKER_NAME
    if marker_path.is_symlink() or not marker_path.is_file():
        raise PermissionError("unowned")
    marker = _read_json(marker_path)
    required = {"schema_version", "owner", "kind", "created_at", "last_touched_at", "artifact_id"}
    if set(marker) != required or marker.get("schema_version") != RETENTION_SCHEMA_VERSION:
        raise ValueError("invalid ownership marker")
    if marker.get("owner") != OWNER or marker.get("kind") != kind.value:
        raise PermissionError("unowned")
    if marker.get("artifact_id") != (expected_artifact_id or path.name):
        raise ValueError("artifact identity mismatch")
    _parse_timestamp(marker.get("created_at"))
    _parse_timestamp(marker.get("last_touched_at"))
    return marker


def _checkpoint_terminal(path: Path) -> bool:
    manifest = _read_json(path / "run.json")
    if manifest.get("checkpoint_contract_version") != CHECKPOINT_CONTRACT_VERSION:
        raise ValueError("unsupported checkpoint contract")
    if manifest.get("run_key") != path.name:
        raise ValueError("checkpoint run key mismatch")
    keys = ("controller", "profile", "reducer_contract_version", "policy_fingerprint",
            "initial_input_fingerprint", "execution_fingerprint")
    if any(not isinstance(manifest.get(key), str) for key in keys):
        raise ValueError("invalid checkpoint manifest")
    store = CheckpointStore(path.parent, run_key=path.name,
        controller=manifest["controller"], profile=manifest["profile"],
        reducer_contract_version=manifest["reducer_contract_version"],
        policy_fingerprint=manifest["policy_fingerprint"],
        initial_input_fingerprint=manifest["initial_input_fingerprint"],
        execution_fingerprint=manifest["execution_fingerprint"])
    state = store.load_highest_completed()
    return state is not None and state.terminal_stop_reason is not None


def _discover(
    roots: Iterable[str | Path | RetentionRoot], limit: int,
) -> tuple[list[tuple[Path, Path, ReductionArtifactKind]], bool, int]:
    found: list[tuple[Path, Path, ReductionArtifactKind]] = []
    scanned = 0

    def consume() -> bool:
        nonlocal scanned
        if scanned >= limit:
            return False
        scanned += 1
        return True

    def scan_item(base: Path) -> bool:
        reductions = [base] if base.name == ".reduction" else [base / ".reduction"]
        for reduction in reductions:
            if reduction.is_symlink() or not reduction.is_dir():
                continue
            for parent, kind in ((reduction / "checkpoints", ReductionArtifactKind.CHECKPOINT_RUN),
                                 (reduction / "runtime", ReductionArtifactKind.RUNTIME_ROUND)):
                if parent.is_symlink() or not parent.is_dir():
                    continue
                for child in os.scandir(parent):
                    if not consume():
                        return False
                    if child.is_dir(follow_symlinks=False):
                        found.append((Path(child.path), parent, kind))
        return True

    for supplied in roots:
        root = supplied if isinstance(supplied, RetentionRoot) else item_retention_root(supplied)
        base = root.path
        if root.kind is RetentionRootKind.PROMPT_CONTAINER:
            if base.is_symlink() or not base.is_dir():
                continue
            for child in os.scandir(base):
                if not consume():
                    return found, True, scanned
                if child.is_dir(follow_symlinks=False) and not scan_item(Path(child.path)):
                    return found, True, scanned
        elif not scan_item(base):
            return found, True, scanned
    return found, False, scanned


def _remove_stale_lease(path: Path, now: datetime) -> None:
    lease = path / LEASE_NAME
    if lease.exists() and not _lease_is_active(path, now):
        if lease.is_dir() and not lease.is_symlink():
            shutil.rmtree(lease)


def _delete_claimed(path: Path, parent: Path, *, token: str) -> None:
    atomic_write_json(str(path / TOMBSTONE_MARKER), {
        "schema_version": 1, "owner": OWNER, "token": token,
        "original_name": path.name,
    })
    tombstone = parent / f".gc-{token}-{path.name}"
    path.rename(tombstone)
    shutil.rmtree(tombstone)


_TOMBSTONE_RE = re.compile(r"^\.gc-([0-9a-f]{32})-(.+)$")


def _validate_tombstone(
    path: Path, parent: Path, kind: ReductionArtifactKind,
) -> tuple[Mapping[str, Any], int]:
    if not _contained_child(path, parent):
        raise ValueError("tombstone escaped approved parent")
    match = _TOMBSTONE_RE.fullmatch(path.name)
    if match is None:
        raise ValueError("invalid tombstone name")
    token, original_name = match.groups()
    expected_name = (
        re.fullmatch(r"[0-9a-f]{64}", original_name)
        if kind is ReductionArtifactKind.CHECKPOINT_RUN
        else re.fullmatch(r"round-[0-9]{4,}", original_name)
    )
    if expected_name is None:
        raise ValueError("invalid original artifact name")
    tomb = _read_json(path / TOMBSTONE_MARKER)
    if set(tomb) != {"schema_version", "owner", "token", "original_name"}:
        raise ValueError("invalid tombstone marker schema")
    if (tomb.get("schema_version") != 1 or tomb.get("owner") != OWNER
            or tomb.get("token") != token or tomb.get("original_name") != original_name):
        raise ValueError("tombstone identity mismatch")
    marker = _validate_marker(path, kind, expected_artifact_id=original_name)
    if marker.get("kind") != kind.value:
        raise ValueError("tombstone artifact kind mismatch")
    return tomb, _tree_size(path)


def run_reduction_retention(
    roots: Iterable[str | Path | RetentionRoot], policy: ReductionRetentionPolicy | Mapping[str, Any] | None,
    *, now: Callable[[], datetime] = _utc_now, observer: Any = None,
) -> RetentionReport:
    policy = parse_reduction_retention_policy(policy)
    report = RetentionReport(dry_run=policy.dry_run)
    if not policy.enabled:
        return report
    if observer is not None:
        observer.emit("reduction_retention_started", {"dry_run": policy.dry_run})
    candidates, scan_hit, scanned = _discover(roots, policy.max_scan_entries_per_sweep)
    report = replace(report, scan_limit_reached=scan_hit, scanned=scanned)
    current = now()
    planned_entries = 0
    planned_bytes = 0
    for path, parent, kind in candidates:
        if path.name.startswith(".gc-"):
            try:
                _tomb, size = _validate_tombstone(path, parent, kind)
            except Exception:
                report = replace(report, skipped_invalid=report.skipped_invalid + 1)
                continue
            report = replace(report, owned=report.owned + 1, eligible=report.eligible + 1)
            if planned_entries >= policy.max_delete_entries_per_sweep or (
                planned_bytes + size > policy.max_delete_bytes_per_sweep
            ):
                report = replace(report, budget_exhausted=True)
                break
            planned_entries += 1
            planned_bytes += size
            if not policy.dry_run:
                try:
                    shutil.rmtree(path)
                    report = replace(
                        report, deleted=report.deleted + 1,
                        bytes_reclaimed=report.bytes_reclaimed + size,
                    )
                except Exception:
                    report = replace(report, errors=report.errors + 1)
            continue
        if not _contained_child(path, parent):
            report = replace(report, skipped_invalid=report.skipped_invalid + 1)
            continue
        try:
            marker = _validate_marker(path, kind)
        except PermissionError:
            report = replace(report, skipped_unowned=report.skipped_unowned + 1)
            continue
        except Exception:
            report = replace(report, skipped_invalid=report.skipped_invalid + 1)
            continue
        report = replace(report, owned=report.owned + 1)
        try:
            terminal = _checkpoint_terminal(path) if kind is ReductionArtifactKind.CHECKPOINT_RUN else False
            touched = _parse_timestamp(marker["last_touched_at"])
            ttl = (timedelta(days=policy.checkpoint_terminal_ttl_days if terminal
                             else policy.checkpoint_incomplete_ttl_days)
                   if kind is ReductionArtifactKind.CHECKPOINT_RUN
                   else timedelta(hours=policy.transient_runtime_ttl_hours))
            age = current - touched
            if age < ttl:
                report = replace(report, skipped_young=report.skipped_young + 1)
                continue
            size = _tree_size(path)
        except Exception:
            report = replace(report, skipped_invalid=report.skipped_invalid + 1)
            continue
        report = replace(report, eligible=report.eligible + 1)
        if _lease_is_active(path, current):
            report = replace(report, skipped_active=report.skipped_active + 1)
            continue
        if planned_entries >= policy.max_delete_entries_per_sweep or (
            planned_bytes + size > policy.max_delete_bytes_per_sweep
        ):
            report = replace(report, budget_exhausted=True)
            break
        planned_entries += 1
        planned_bytes += size
        if policy.dry_run:
            continue
        claim = path / GC_CLAIM_NAME
        try:
            claim.mkdir()
            atomic_write_json(str(claim / "claim.json"), {
                "schema_version": 1, "owner": OWNER,
                "token": secrets.token_hex(16), "claimed_at": _timestamp(current),
            })
            # Claim-before-delete revalidation.
            marker = _validate_marker(path, kind)
            if not _contained_child(path, parent):
                raise ValueError("artifact escaped approved parent")
            terminal2 = _checkpoint_terminal(path) if kind is ReductionArtifactKind.CHECKPOINT_RUN else False
            touched2 = _parse_timestamp(marker["last_touched_at"])
            ttl2 = (timedelta(days=policy.checkpoint_terminal_ttl_days if terminal2
                              else policy.checkpoint_incomplete_ttl_days)
                    if kind is ReductionArtifactKind.CHECKPOINT_RUN
                    else timedelta(hours=policy.transient_runtime_ttl_hours))
            if _lease_is_active(path, current) or current - touched2 < ttl2:
                shutil.rmtree(claim)
                report = replace(report, skipped_active=report.skipped_active + 1)
                continue
            size2 = _tree_size(path)
            if planned_bytes - size + size2 > policy.max_delete_bytes_per_sweep:
                shutil.rmtree(claim)
                report = replace(report, budget_exhausted=True)
                break
            _remove_stale_lease(path, current)
            claim_data = _read_json(claim / "claim.json")
            _delete_claimed(path, parent, token=claim_data["token"])
            report = replace(report, deleted=report.deleted + 1,
                             bytes_reclaimed=report.bytes_reclaimed + size2)
        except Exception:
            report = replace(report, errors=report.errors + 1)
            if claim.is_dir() and path.exists():
                shutil.rmtree(claim, ignore_errors=True)
    if observer is not None:
        observer.emit("reduction_retention_completed", report.safe_summary())
    return report


def cleanup_completed_transient_runtime(
    item_workspace: str | Path, policy: ReductionRetentionPolicy | Mapping[str, Any] | None,
    *, now: Callable[[], datetime] = _utc_now, observer: Any = None,
) -> RetentionReport:
    parsed = parse_reduction_retention_policy(policy)
    if not parsed.enabled or not parsed.cleanup_transient_on_success:
        return RetentionReport(dry_run=parsed.dry_run)
    immediate = replace(parsed, transient_runtime_ttl_hours=0)
    return run_reduction_retention([item_workspace], immediate, now=now, observer=observer)
