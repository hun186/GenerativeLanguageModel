from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from czjLLM.reduction.controllers import FixedRoundsController
from czjLLM.reduction.hierarchical import reduce_hierarchical_text
from czjLLM.reduction.retention import (
    ArtifactLease,
    ReductionArtifactKind,
    ReductionRetentionPolicy,
    parse_reduction_retention_policy,
    run_reduction_retention,
    write_artifact_marker,
)


NOW = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)


def _terminal(item: Path, *, stamp: datetime = NOW - timedelta(days=20)) -> Path:
    result = reduce_hierarchical_text(
        ["a\n", "b\n"], profile="concat_text",
        controller=FixedRoundsController(rounds=1),
        next_round_items=lambda *_: pytest.fail("one round must not prepare another"),
        checkpoint_root=item / ".reduction" / "checkpoints",
        execution_fingerprint="execution-v1",
    )
    assert result.payload == "a\nb\n"
    run_dir = next((item / ".reduction" / "checkpoints").iterdir())
    write_artifact_marker(run_dir, kind=ReductionArtifactKind.CHECKPOINT_RUN,
                          artifact_id=run_dir.name, now=lambda: stamp)
    return run_dir


def _runtime(item: Path, name: str, stamp: datetime) -> Path:
    path = item / ".reduction" / "runtime" / name
    (path / "TODO").mkdir(parents=True)
    (path / "TODO" / "work.txt").write_text("payload", encoding="utf-8")
    write_artifact_marker(path, kind=ReductionArtifactKind.RUNTIME_ROUND,
                          artifact_id=name, now=lambda: stamp)
    return path


def test_strict_policy_defaults_types_limits_and_ttl_relationship():
    assert parse_reduction_retention_policy(None) == ReductionRetentionPolicy()
    assert not ReductionRetentionPolicy().enabled
    with pytest.raises(ValueError, match="unknown"):
        parse_reduction_retention_policy({"surprise": True})
    with pytest.raises(TypeError, match="bool"):
        parse_reduction_retention_policy({"enabled": 1})
    for value in (float("nan"), float("inf"), -1):
        with pytest.raises(ValueError):
            parse_reduction_retention_policy({"checkpoint_terminal_ttl_days": value})
    with pytest.raises(ValueError, match="incomplete TTL"):
        parse_reduction_retention_policy({
            "checkpoint_terminal_ttl_days": 31,
            "checkpoint_incomplete_ttl_days": 30,
        })
    with pytest.raises(ValueError, match="positive integer"):
        parse_reduction_retention_policy({"max_delete_entries_per_sweep": True})


def test_terminal_and_incomplete_checkpoint_ttl_and_corruption(tmp_path: Path):
    terminal = _terminal(tmp_path / "terminal")
    young = _terminal(tmp_path / "young", stamp=NOW - timedelta(days=2))
    # Removing the committed terminal round makes this a valid incomplete run.
    incomplete = _terminal(tmp_path / "incomplete", stamp=NOW - timedelta(days=20))
    for child in incomplete.glob("round-*"):
        child.unlink()
    corrupt = _terminal(tmp_path / "corrupt")
    (corrupt / "run.json").write_text("{broken", encoding="utf-8")
    policy = ReductionRetentionPolicy(enabled=True)
    report = run_reduction_retention(
        [tmp_path / name for name in ("terminal", "young", "incomplete", "corrupt")],
        policy, now=lambda: NOW,
    )
    assert not terminal.exists()
    assert young.exists() and incomplete.exists() and corrupt.exists()
    assert report.deleted == 1
    assert report.skipped_young == 2
    assert report.skipped_invalid == 1


def test_active_and_stale_cross_process_lease(tmp_path: Path):
    item = tmp_path / "item"
    runtime = _runtime(item, "round-0002", NOW - timedelta(days=3))
    lease = ArtifactLease(runtime, now=lambda: NOW).acquire()
    active = run_reduction_retention([item], ReductionRetentionPolicy(enabled=True), now=lambda: NOW)
    assert runtime.exists() and active.skipped_active == 1
    lease.release()
    deleted = run_reduction_retention([item], ReductionRetentionPolicy(enabled=True), now=lambda: NOW)
    assert deleted.deleted == 1 and not runtime.exists()

    stale = _runtime(item, "round-0003", NOW - timedelta(days=3))
    lease = ArtifactLease(stale, now=lambda: NOW - timedelta(days=1)).acquire()
    # Deliberately do not release: the six-hour lease is stale at NOW.
    report = run_reduction_retention([item], ReductionRetentionPolicy(enabled=True), now=lambda: NOW)
    assert report.deleted == 1 and not stale.exists()
    lease.acquired = False


def test_unowned_symlink_and_containment_are_never_deleted(tmp_path: Path):
    item = tmp_path / "item"
    parent = item / ".reduction" / "runtime"
    unowned = parent / "round-0002"
    unowned.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("keep", encoding="utf-8")
    link = parent / "round-0003"
    link.symlink_to(outside, target_is_directory=True)
    report = run_reduction_retention([item], ReductionRetentionPolicy(enabled=True), now=lambda: NOW)
    assert unowned.exists() and link.is_symlink() and (outside / "secret.txt").exists()
    assert report.skipped_unowned == 1


def test_dry_run_entry_and_byte_budgets(tmp_path: Path):
    item = tmp_path / "item"
    paths = [_runtime(item, f"round-{index:04d}", NOW - timedelta(days=3))
             for index in range(2, 5)]
    dry = run_reduction_retention(
        [item], replace(ReductionRetentionPolicy(enabled=True), dry_run=True), now=lambda: NOW)
    assert dry.eligible == 3 and dry.deleted == 0 and all(path.exists() for path in paths)
    bounded = run_reduction_retention(
        [item], replace(ReductionRetentionPolicy(enabled=True),
                        max_delete_entries_per_sweep=1), now=lambda: NOW)
    assert bounded.deleted == 1 and bounded.budget_exhausted
    remaining = [path for path in paths if path.exists()]
    byte_limited = run_reduction_retention(
        [item], replace(ReductionRetentionPolicy(enabled=True),
                        max_delete_bytes_per_sweep=1), now=lambda: NOW)
    assert byte_limited.deleted == 0 and byte_limited.budget_exhausted
    assert all(path.exists() for path in remaining)


def test_marker_report_and_observer_are_bounded_and_secret_free(tmp_path: Path):
    secret = "sk-very-secret-key"
    item = tmp_path / secret
    runtime = _runtime(item, "round-0002", NOW - timedelta(days=3))

    class Observer:
        events = []
        def emit(self, event, fields):
            self.events.append((event, dict(fields)))

    observer = Observer()
    report = run_reduction_retention(
        [item], ReductionRetentionPolicy(enabled=True, dry_run=True),
        now=lambda: NOW, observer=observer)
    serialized = json.dumps({"report": asdict(report), "events": observer.events,
                             "marker": json.loads((runtime / ".retention.json").read_text())})
    assert secret not in serialized
    assert "https://private-endpoint.example" not in serialized
    assert not hasattr(report, "paths")


def test_retention_policy_is_not_part_of_execution_fingerprint(tmp_path: Path):
    def run(policy):
        # The policy is intentionally not an argument to hierarchical execution.
        return reduce_hierarchical_text(
            ["x"], profile="concat_text", controller=FixedRoundsController(rounds=1),
            next_round_items=lambda *_: [], checkpoint_root=tmp_path / "checkpoints",
            execution_fingerprint="same-semantic-execution",
        )
    run(ReductionRetentionPolicy(checkpoint_terminal_ttl_days=7))
    key1 = next((tmp_path / "checkpoints").iterdir()).name
    run(ReductionRetentionPolicy(checkpoint_terminal_ttl_days=30))
    assert [path.name for path in (tmp_path / "checkpoints").iterdir()] == [key1]


def test_only_verifiable_gc_tombstone_is_recovered(tmp_path: Path):
    item = tmp_path / "item"
    runtime = _runtime(item, "round-0002", NOW - timedelta(days=3))
    parent = runtime.parent
    token = "0123456789abcdef"
    (runtime / ".gc-tombstone.json").write_text(json.dumps({
        "schema_version": 1, "owner": "czjLLM.reduction", "token": token,
        "original_name": runtime.name,
    }), encoding="utf-8")
    tombstone = parent / f".gc-{token}-{runtime.name}"
    runtime.rename(tombstone)
    arbitrary = parent / ".gc-not-ours"
    arbitrary.mkdir()
    report = run_reduction_retention([item], ReductionRetentionPolicy(enabled=True), now=lambda: NOW)
    assert not tombstone.exists()
    assert arbitrary.exists()
    assert report.skipped_invalid == 1
