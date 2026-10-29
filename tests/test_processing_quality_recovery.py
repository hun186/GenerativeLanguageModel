"""Actual-file interrupted-rotation rollback tests: no model/network/database."""
from __future__ import annotations

import json
import os

import pytest

from czjLLM.cli_tools.processing_quality_recover import main
from czjLLM.cli_tools.processing_quality_report import report_for_audit
from czjLLM.utilities.processing_quality import emit_quality_event, quality_event_path
from czjLLM.utilities.processing_quality_manifest import (
    initialize_quality_manifest, manifest_path, verify_quality_manifest,
)
from czjLLM.utilities.processing_quality_recovery import (
    inspect_interrupted_rotation, rollback_interrupted_rotation,
)
from czjLLM.utilities.processing_quality_rotation import (
    quality_stream_segments, rotate_quality_event_stream,
)


def _emit(audit, *, event="worker_phase_failure", code="WORKER_LLM_TIMEOUT_EXCEPTION"):
    emit_quality_event(
        str(audit), run_id="safe", event=event, code=code,
        scope="run", outcome="observed",
    )


def _sealed_one(audit):
    _emit(audit)
    active = quality_event_path(str(audit))
    rotate_quality_event_stream(audit)
    initialize_quality_manifest(audit)
    assert verify_quality_manifest(active)["sealed_segments"] == 1
    return active


def _simulate_crash_after_rename(audit):
    active = quality_event_path(str(audit))
    original = active.read_bytes()
    extra = active.with_name(active.name + ".seg-00000002")
    os.rename(active, extra)
    return original, extra


def test_inspect_and_explicit_rollback_preserve_bytes_and_original_ledger(tmp_path, capsys):
    audit = tmp_path / "llm_call_audit_20261024-crash.csv"
    active = _sealed_one(audit)
    ledger = manifest_path(active).read_bytes()
    sealed = quality_stream_segments(active)[0].read_bytes()
    _emit(audit, event="stage_orchestration_failure", code="STAGE_PREPARE_EXCEPTION")
    original, extra = _simulate_crash_after_rename(audit)
    assert not active.exists()
    before = extra.read_bytes()
    state = inspect_interrupted_rotation(audit)
    assert state == {
        "status": "rollback_candidate", "sealed_segments": 1,
        "archived_segments": 2, "active_present": False,
    }
    with pytest.raises(ValueError, match="count differs"):
        report_for_audit(audit)
    # Read-only CLI creates no files and exposes no paths/payload.
    assert main(["--audit-path", str(audit)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "rollback_candidate"
    assert not active.exists() and extra.read_bytes() == before
    with pytest.raises(SystemExit) as e:
        main(["--audit-path", str(audit), "--rollback"])
    assert e.value.code == 2
    capsys.readouterr()
    assert main(["--audit-path", str(audit), "--rollback", "--confirm-stopped"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result == {
        "mode": "quality_rotation_recovery",
        "status": "rolled_back_to_active_unsealed",
        "sealed_segments": 1,
        "restored_active": True,
    }
    assert "crash" not in json.dumps(result)
    assert active.read_bytes() == original
    assert not extra.exists()
    assert manifest_path(active).read_bytes() == ledger
    assert quality_stream_segments(active)[0].read_bytes() == sealed
    assert verify_quality_manifest(active)["sealed_segments"] == 1
    stats = report_for_audit(audit)["run"]
    assert stats["metrics"]["worker_phase_failure_events"] == 1
    assert stats["metrics"]["stage_orchestration_failure_events"] == 1
    # The restored data is now an active, unsealed generation; it can be rotated
    # and sealed by the normal existing path when the operator is ready.
    assert rotate_quality_event_stream(audit)["archived_segments"] == 2
    assert verify_quality_manifest(active)["sealed_segments"] == 2
    assert report_for_audit(audit)["run"]["metrics"]["events"] == 2
    with pytest.raises(ValueError, match="not unambiguously eligible"):
        rollback_interrupted_rotation(audit)


def test_existing_active_blocks_rollback_without_altering_any_archive(tmp_path):
    audit = tmp_path / "llm_call_audit_20261024-collision.csv"
    active = _sealed_one(audit)
    _emit(audit)
    _, extra = _simulate_crash_after_rename(audit)
    preserved = extra.read_bytes()
    _emit(audit, event="producer_operational_failure", code="PRODUCER_FUTURE_EXCEPTION")
    current = active.read_bytes()
    assert inspect_interrupted_rotation(audit)["status"] == "ambiguous_active_present"
    with pytest.raises(ValueError, match="not unambiguously eligible"):
        rollback_interrupted_rotation(audit)
    assert extra.read_bytes() == preserved
    assert active.read_bytes() == current


def test_missing_or_corrupt_prior_sealed_archive_fails_closed(tmp_path):
    audit = tmp_path / "llm_call_audit_20261024-tamper.csv"
    active = _sealed_one(audit)
    _emit(audit)
    _, extra = _simulate_crash_after_rename(audit)
    original = extra.read_bytes()
    first = quality_stream_segments(active)[0]
    first.write_bytes(first.read_bytes().replace(b"TIMEOUT", b"INVALID"))
    with pytest.raises(ValueError, match="sealed quality archive mismatch"):
        inspect_interrupted_rotation(audit)
    with pytest.raises(ValueError):
        rollback_interrupted_rotation(audit)
    assert extra.read_bytes() == original
    assert not active.exists()


def test_two_unsealed_extra_shards_cannot_be_guessed_or_restored(tmp_path):
    audit = tmp_path / "llm_call_audit_20261024-two.csv"
    active = _sealed_one(audit)
    _emit(audit)
    _, extra = _simulate_crash_after_rename(audit)
    extra2 = active.with_name(active.name + ".seg-00000003")
    extra2.write_bytes(extra.read_bytes())
    with pytest.raises(ValueError, match="does not admit safe rollback"):
        inspect_interrupted_rotation(audit)
    with pytest.raises(ValueError):
        rollback_interrupted_rotation(audit)
    assert extra.exists() and extra2.exists() and not active.exists()


def test_unsealed_legacy_archives_are_not_auto_rebaselined(tmp_path):
    audit = tmp_path / "llm_call_audit_20261024-legacy.csv"
    _emit(audit)
    active = quality_event_path(str(audit))
    rotate_quality_event_stream(audit)
    assert inspect_interrupted_rotation(audit)["status"] == "unsealed_legacy"
    with pytest.raises(ValueError):
        rollback_interrupted_rotation(audit)
    assert not manifest_path(active).exists()
    assert len(quality_stream_segments(active)) == 1


def test_tampered_or_missing_manifest_cannot_be_silently_extended(tmp_path):
    audit = tmp_path / "llm_call_audit_20261024-ledger.csv"
    active = _sealed_one(audit)
    _emit(audit)
    _, extra = _simulate_crash_after_rename(audit)
    manifest = manifest_path(active)
    old = manifest.read_bytes()
    manifest.write_bytes(old.replace(b'"ledger_sha256":"', b'"ledger_sha256":"f', 1))
    with pytest.raises(ValueError):
        inspect_interrupted_rotation(audit)
    with pytest.raises(ValueError):
        rollback_interrupted_rotation(audit)
    assert extra.exists() and not active.exists()
    manifest.write_bytes(old)
    manifest.unlink()
    assert inspect_interrupted_rotation(audit)["status"] == "unsealed_legacy"
    with pytest.raises(ValueError):
        rollback_interrupted_rotation(audit)


def test_symlinks_and_invalid_audit_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="invalid per-run"):
        inspect_interrupted_rotation(tmp_path / "unrelated.csv")
    audit = tmp_path / "llm_call_audit_20261024-link.csv"
    active = _sealed_one(audit)
    _emit(audit)
    _, extra = _simulate_crash_after_rename(audit)
    target = tmp_path / "unsafe-active-file"
    target.write_bytes(b"private\n")
    try:
        active.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink unsupported")
    with pytest.raises(ValueError, match="symlink"):
        inspect_interrupted_rotation(audit)
    with pytest.raises(ValueError, match="symlink"):
        rollback_interrupted_rotation(audit)
    assert extra.exists() and target.read_bytes() == b"private\n"


def test_interrupt_after_exclusive_link_retains_both_names_without_data_loss(tmp_path, monkeypatch):
    """Second crash during repair must preserve bytes, not overwrite or delete."""
    from pathlib import Path

    audit = tmp_path / "llm_call_audit_20261024-interrupted-repair.csv"
    active = _sealed_one(audit)
    _emit(audit, event="stage_orchestration_failure", code="STAGE_PREPARE_EXCEPTION")
    raw, candidate = _simulate_crash_after_rename(audit)
    baseline = manifest_path(active).read_bytes()
    actual_unlink = Path.unlink

    def refuse_candidate_unlink(self, *args, **kwargs):
        if self == candidate:
            raise OSError("simulated second interruption")
        return actual_unlink(self, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", refuse_candidate_unlink)
        with pytest.raises(OSError, match="second interruption"):
            rollback_interrupted_rotation(audit)

    assert active.read_bytes() == raw
    assert candidate.read_bytes() == raw
    assert manifest_path(active).read_bytes() == baseline
    assert inspect_interrupted_rotation(audit)["status"] == "ambiguous_active_present"
    with pytest.raises(ValueError, match="not unambiguously eligible"):
        rollback_interrupted_rotation(audit)
    # Neither name is silently removed in an ambiguous state.
    assert active.exists() and candidate.exists()


def test_sealed_archive_hardlink_candidate_fails_closed(tmp_path):
    """An extra link to a sealed inode must never become writable active JSONL."""
    audit = tmp_path / "llm_call_audit_20261029-linked-sealed.csv"
    active = _sealed_one(audit)
    first = quality_stream_segments(active)[0]
    sealed_bytes = first.read_bytes()
    ledger_bytes = manifest_path(active).read_bytes()
    extra = active.with_name(active.name + ".seg-00000002")
    try:
        os.link(first, extra)
    except (OSError, NotImplementedError):
        pytest.skip("filesystem does not support hardlinks")
    assert not active.exists() and first.stat().st_nlink >= 2
    with pytest.raises(ValueError, match="unsafe hardlink"):
        inspect_interrupted_rotation(audit)
    with pytest.raises(ValueError, match="unsafe hardlink"):
        rollback_interrupted_rotation(audit)
    assert not active.exists()
    assert first.read_bytes() == sealed_bytes
    assert extra.read_bytes() == sealed_bytes
    assert manifest_path(active).read_bytes() == ledger_bytes
    extra.unlink()
    assert verify_quality_manifest(active)["sealed_segments"] == 1


def test_external_hardlink_candidate_is_not_recovered(tmp_path):
    """Even a hardlink outside the shard namespace is an unsafe candidate."""
    audit = tmp_path / "llm_call_audit_20261029-linked-other.csv"
    active = _sealed_one(audit)
    _emit(audit)
    original, candidate = _simulate_crash_after_rename(audit)
    external_alias = tmp_path / "another-quality-name"
    try:
        os.link(candidate, external_alias)
    except (OSError, NotImplementedError):
        pytest.skip("filesystem does not support hardlinks")
    with pytest.raises(ValueError, match="unsafe hardlink"):
        inspect_interrupted_rotation(audit)
    with pytest.raises(ValueError, match="unsafe hardlink"):
        rollback_interrupted_rotation(audit)
    assert not active.exists()
    assert candidate.read_bytes() == original
    assert external_alias.read_bytes() == original
