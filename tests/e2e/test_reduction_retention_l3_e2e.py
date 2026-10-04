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
    run_reduction_retention,
    prompt_container_retention_root,
    write_artifact_marker,
)


pytestmark = pytest.mark.e2e


def test_reduction_retention_l3_checkpoint_gc_resume_identity_and_privacy(tmp_path):
    """One hosted case with real checkpoint, protection, aging, resume and privacy phases."""
    now = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)
    item = tmp_path / "Prompt" / "item"
    checkpoints = item / ".reduction" / "checkpoints"
    semantic = dict(
        initial_items=["alpha\n", "beta\n"], profile="concat_text",
        controller=FixedRoundsController(rounds=2),
        next_round_items=lambda payload, _round: [payload.upper()],
        checkpoint_root=checkpoints, execution_fingerprint="e2e-semantic-v1",
    )

    # Phase A: actual reducer/controller/store produce and resume a terminal chain.
    first = reduce_hierarchical_text(**semantic)
    resumed = reduce_hierarchical_text(**semantic)
    assert resumed.payload == first.payload == "ALPHA\nBETA\n"
    assert resumed.resumed_rounds == 2
    terminal = next(checkpoints.iterdir())

    # Phase B/C: protected artifacts and deterministic aging.
    final_output = tmp_path / "Finished" / "item.txt"
    final_output.parent.mkdir()
    final_output.write_text(first.payload, encoding="utf-8")
    manifest = tmp_path / "caller-selected-collection-manifest.json"
    manifest.write_text('{"owned":"caller"}', encoding="utf-8")
    unowned_item = tmp_path / "Prompt" / "unmarked-old-item"
    unowned = unowned_item / ".reduction" / "checkpoints" / ("f" * 64)
    unowned.mkdir(parents=True)
    runtime_parent = item / ".reduction" / "runtime"
    expired_runtime = runtime_parent / "round-0003"
    (expired_runtime / "TODO").mkdir(parents=True)
    write_artifact_marker(expired_runtime, kind=ReductionArtifactKind.RUNTIME_ROUND,
                          artifact_id=expired_runtime.name,
                          now=lambda: now - timedelta(days=2))
    active_runtime = runtime_parent / "round-0004"
    (active_runtime / "TODO").mkdir(parents=True)
    write_artifact_marker(active_runtime, kind=ReductionArtifactKind.RUNTIME_ROUND,
                          artifact_id=active_runtime.name,
                          now=lambda: now - timedelta(days=2))
    active_lease = ArtifactLease(active_runtime, now=lambda: now).acquire()
    write_artifact_marker(terminal, kind=ReductionArtifactKind.CHECKPOINT_RUN,
                          artifact_id=terminal.name,
                          now=lambda: now - timedelta(days=15))

    policy = ReductionRetentionPolicy(enabled=True)
    unrelated = tmp_path / "Prompt" / "unrelated-dir" / "nested-item"
    nested_runtime = unrelated / ".reduction" / "runtime" / "round-0002"
    (nested_runtime / "TODO").mkdir(parents=True)
    write_artifact_marker(nested_runtime, kind=ReductionArtifactKind.RUNTIME_ROUND,
                          artifact_id=nested_runtime.name,
                          now=lambda: now - timedelta(days=2))
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "Prompt" / "symlink-outside").symlink_to(outside, target_is_directory=True)

    # Only the prompt container is approved: the expired historical direct-child
    # item is found without being part of a current scheduler/seen set.
    report = run_reduction_retention(
        [prompt_container_retention_root(tmp_path / "Prompt")], policy, now=lambda: now)
    assert not terminal.exists() and not expired_runtime.exists()
    assert active_runtime.exists() and unowned.exists()
    assert nested_runtime.exists() and outside.exists()
    assert final_output.read_text(encoding="utf-8") == first.payload
    assert manifest.exists()
    active_lease.release()

    # Crash tombstone recovery has exact identity validation and shares budgets.
    recovery_item = tmp_path / "RecoveryPrompt" / "old-item"
    recovery_parent = recovery_item / ".reduction" / "runtime"

    def tombstone(name, token):
        path = recovery_parent / name
        (path / "TODO").mkdir(parents=True)
        write_artifact_marker(path, kind=ReductionArtifactKind.RUNTIME_ROUND,
                              artifact_id=name, now=lambda: now - timedelta(days=2))
        (path / ".gc-tombstone.json").write_text(json.dumps({
            "schema_version": 1, "owner": "czjLLM.reduction", "token": token,
            "original_name": name,
        }), encoding="utf-8")
        target = recovery_parent / f".gc-{token}-{name}"
        path.rename(target)
        return target

    invalid = tombstone("round-0005", "2" * 32)
    invalid.rename(recovery_parent / f".gc-{'2' * 32}-wrong-name")
    invalid = recovery_parent / f".gc-{'2' * 32}-wrong-name"
    valid_one = tombstone("round-0006", "3" * 32)
    valid_two = tombstone("round-0007", "4" * 32)
    recovery = run_reduction_retention(
        [prompt_container_retention_root(tmp_path / "RecoveryPrompt")],
        replace(policy, max_delete_entries_per_sweep=1), now=lambda: now,
    )
    assert invalid.exists()
    assert sum(path.exists() for path in (valid_one, valid_two)) == 1
    assert recovery.deleted == 1 and recovery.budget_exhausted
    assert recovery.skipped_invalid == 1

    # Phase D: a removed deterministic run rebuilds with the same key/output.
    rebuilt = reduce_hierarchical_text(**semantic)
    rebuilt_dir = next(checkpoints.iterdir())
    assert rebuilt_dir.name == terminal.name
    assert rebuilt.payload == first.payload

    # Phase E: summaries/markers contain bounded operational data, never runtime secrets.
    secret_blob = "SECRET RAW PROMPT sk-very-secret-key https://private-endpoint.example Server=secret"
    serialized = json.dumps(asdict(report), sort_keys=True)
    serialized += (rebuilt_dir / ".retention.json").read_text(encoding="utf-8")
    assert secret_blob not in serialized
    for secret in secret_blob.split():
        assert secret not in serialized
    assert report.deleted == 2 and report.skipped_active == 1
