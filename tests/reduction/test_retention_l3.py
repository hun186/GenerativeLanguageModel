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
    project_reduction_retention_policy,
    prompt_container_retention_root,
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


def _tombstone(item: Path, name: str, token: str, *, payload_size: int = 0) -> Path:
    runtime = _runtime(item, name, NOW - timedelta(days=3))
    if payload_size:
        (runtime / "TODO" / "large.bin").write_bytes(b"x" * payload_size)
    (runtime / ".gc-tombstone.json").write_text(json.dumps({
        "schema_version": 1, "owner": "czjLLM.reduction", "token": token,
        "original_name": name,
    }), encoding="utf-8")
    tombstone = runtime.parent / f".gc-{token}-{name}"
    runtime.rename(tombstone)
    return tombstone


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


def test_root_yaml_projection_uses_canonical_production_boundary():
    class Context:
        pass

    configured = Context()
    project_reduction_retention_policy(configured, lambda key, default=None: {
        "reduction_retention": {
            "enabled": True, "checkpoint_terminal_ttl_days": 7,
        }
    }.get(key, default))
    assert isinstance(configured.reduction_retention, ReductionRetentionPolicy)
    assert configured.reduction_retention.enabled
    assert configured.reduction_retention.checkpoint_terminal_ttl_days == 7

    absent = Context()
    project_reduction_retention_policy(absent, lambda _key, default=None: default)
    assert absent.reduction_retention == ReductionRetentionPolicy()

    production_source = Path("czjLLM/czjLLM_TextProcessing.py").read_text(encoding="utf-8")
    assert "project_reduction_retention_policy(ctx, get_param)" in production_source


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

    young = _runtime(item, "round-0004", NOW - timedelta(hours=1))
    stale_young_lease = ArtifactLease(young, now=lambda: NOW - timedelta(days=1)).acquire()
    kept = run_reduction_retention([item], ReductionRetentionPolicy(enabled=True), now=lambda: NOW)
    assert young.exists() and kept.skipped_young == 1
    stale_young_lease.release()

    claimed = _runtime(item, "round-0005", NOW - timedelta(days=3))
    (claimed / ".gc-claim").mkdir()
    with pytest.raises(RuntimeError, match="claimed"):
        ArtifactLease(claimed, now=lambda: NOW).acquire()


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


def test_prompt_container_finds_historical_direct_child_only(tmp_path: Path):
    prompt = tmp_path / "Prompt"
    (prompt / "current-item").mkdir(parents=True)
    historical = _terminal(prompt / "expired-old-item")
    unrelated = prompt / "unrelated-dir" / "nested-item"
    nested = _runtime(unrelated, "round-0002", NOW - timedelta(days=3))
    outside = tmp_path / "outside"
    outside.mkdir()
    link = prompt / "symlink-outside"
    link.symlink_to(outside, target_is_directory=True)

    report = run_reduction_retention(
        [prompt_container_retention_root(prompt)],
        ReductionRetentionPolicy(enabled=True), now=lambda: NOW,
    )
    assert not historical.exists()
    assert nested.exists()  # no recursive descent below one approved item level
    assert link.is_symlink() and outside.exists()
    assert report.deleted == 1


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
    class Context:
        pass

    def run(terminal_ttl):
        ctx = Context()
        project_reduction_retention_policy(ctx, lambda key, default=None: {
            "reduction_retention": {"checkpoint_terminal_ttl_days": terminal_ttl}
        }.get(key, default))
        assert ctx.reduction_retention.checkpoint_terminal_ttl_days == terminal_ttl
        # The policy is intentionally not an argument to hierarchical execution.
        return reduce_hierarchical_text(
            ["x"], profile="concat_text", controller=FixedRoundsController(rounds=1),
            next_round_items=lambda *_: [], checkpoint_root=tmp_path / "checkpoints",
            execution_fingerprint="same-semantic-execution",
        )
    run(7)
    key1 = next((tmp_path / "checkpoints").iterdir()).name
    run(30)
    assert [path.name for path in (tmp_path / "checkpoints").iterdir()] == [key1]


def test_tombstone_recovery_identity_and_entry_budget(tmp_path: Path):
    item = tmp_path / "item"
    malformed = _tombstone(item, "round-0004", "2" * 32)
    malformed.rename(malformed.parent / f".gc-{'2' * 32}-wrong-name")
    malformed = malformed.parent / f".gc-{'2' * 32}-wrong-name"
    first = _tombstone(item, "round-0002", "0" * 32)
    second = _tombstone(item, "round-0003", "1" * 32)
    report = run_reduction_retention(
        [item], replace(ReductionRetentionPolicy(enabled=True),
                        max_delete_entries_per_sweep=1), now=lambda: NOW)
    assert sum(path.exists() for path in (first, second)) == 1
    assert malformed.exists()
    assert report.deleted == 1 and report.eligible == 2
    assert report.budget_exhausted
    assert report.skipped_invalid == 1


def test_budget_exhaustion_still_classifies_later_invalid_tombstone(tmp_path: Path):
    first_item = tmp_path / "first"
    second_item = tmp_path / "second"
    invalid_item = tmp_path / "invalid"

    first = _tombstone(first_item, "round-0002", "0" * 32)
    second = _tombstone(second_item, "round-0003", "1" * 32)
    malformed = _tombstone(invalid_item, "round-0004", "2" * 32)
    malformed.rename(malformed.parent / f".gc-{'2' * 32}-wrong-name")
    malformed = malformed.parent / f".gc-{'2' * 32}-wrong-name"

    report = run_reduction_retention(
        [first_item, second_item, invalid_item],
        replace(ReductionRetentionPolicy(enabled=True), max_delete_entries_per_sweep=1),
        now=lambda: NOW,
    )

    assert not first.exists()
    assert second.exists()
    assert malformed.exists()
    assert report.deleted == 1
    assert report.eligible == 2
    assert report.budget_exhausted
    assert report.skipped_invalid == 1


def test_tombstone_recovery_obeys_byte_budget_and_dry_run(tmp_path: Path):
    item = tmp_path / "item"
    large = _tombstone(item, "round-0002", "a" * 32, payload_size=2048)
    policy = replace(ReductionRetentionPolicy(enabled=True), max_delete_bytes_per_sweep=100)
    report = run_reduction_retention([item], policy, now=lambda: NOW)
    assert large.exists() and report.deleted == 0 and report.budget_exhausted

    dry = run_reduction_retention([item], replace(policy, dry_run=True), now=lambda: NOW)
    assert large.exists() and dry.eligible == 1 and dry.deleted == 0


def test_pre_l3_checkpoint_resume_remains_unmarked_and_unowned(tmp_path: Path):
    item = tmp_path / "legacy"
    run_dir = _terminal(item)
    (run_dir / ".retention.json").unlink()
    resumed = reduce_hierarchical_text(
        ["a\n", "b\n"], profile="concat_text",
        controller=FixedRoundsController(rounds=1),
        next_round_items=lambda *_: pytest.fail("terminal resume must not continue"),
        checkpoint_root=item / ".reduction" / "checkpoints",
        execution_fingerprint="execution-v1",
    )
    assert resumed.resumed_rounds == 1
    assert not (run_dir / ".retention.json").exists()
    report = run_reduction_retention([item], ReductionRetentionPolicy(enabled=True), now=lambda: NOW)
    assert run_dir.exists() and report.skipped_unowned == 1 and report.deleted == 0
