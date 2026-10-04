from __future__ import annotations

import json
from dataclasses import asdict
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
    unowned = checkpoints / ("f" * 64)
    unowned.mkdir()
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
    report = run_reduction_retention([item], policy, now=lambda: now)
    assert not terminal.exists() and not expired_runtime.exists()
    assert active_runtime.exists() and unowned.exists()
    assert final_output.read_text(encoding="utf-8") == first.payload
    assert manifest.exists()
    active_lease.release()

    # Phase D: a removed deterministic run rebuilds with the same key/output.
    rebuilt = reduce_hierarchical_text(**semantic)
    rebuilt_dir = next(path for path in checkpoints.iterdir() if path.name != unowned.name)
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
