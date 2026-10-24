"""Actual-file opt-in JSONL archive sealing/replay, no model/DB/network."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from czjLLM.cli_tools.processing_quality_manifest import main
from czjLLM.cli_tools.processing_quality_report import report_for_audit, report_history
from czjLLM.utilities.processing_quality import emit_quality_event, quality_event_path
from czjLLM.utilities.processing_quality_rotation import (
    rotate_quality_event_stream, quality_stream_segments,
)
from czjLLM.utilities.processing_quality_manifest import (
    initialize_quality_manifest, manifest_path, verify_quality_manifest,
)


def emit(audit, event="worker_phase_failure", code="WORKER_LLM_TIMEOUT_EXCEPTION",
         *, document_id="", scope="run"):
    emit_quality_event(
        str(audit), run_id="safe", event=event, code=code, scope=scope,
        outcome="observed", document_id=document_id,
    )


def test_legacy_archive_requires_explicit_sealing_and_old_report_stays_readable(tmp_path):
    audit = tmp_path / "llm_call_audit_20261024-unsealed.csv"
    emit(audit)
    active = quality_event_path(str(audit))
    rotate_quality_event_stream(audit)
    assert not manifest_path(active).exists()
    result = report_for_audit(audit)["run"]
    assert result["state"] == "observed"
    assert result["archive_integrity"] == {
        "status": "unsealed_legacy", "sealed_segments": 0,
    }
    assert result["metrics"]["worker_phase_failure_events"] == 1
    assert report_history(tmp_path)["runs"][0]["archive_integrity"]["status"] == "unsealed_legacy"


def test_explicit_stopped_seal_then_rotation_updates_manifest_and_maintains_recovery(tmp_path, capsys):
    audit = tmp_path / "llm_call_audit_20261024-sealed.csv"
    emit(audit, "document_schema_rejected", "SCHEMA_OTHER",
         document_id="private-key", scope="document")
    emit(audit)
    active = quality_event_path(str(audit))
    rotate_quality_event_stream(audit)
    assert not manifest_path(active).exists()
    with pytest.raises(SystemExit) as e:
        main(["--audit-path", str(audit), "--initialize"])
    assert e.value.code == 2
    capsys.readouterr()
    assert main(["--audit-path", str(audit), "--initialize", "--confirm-stopped"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output == {"mode": "quality_archive_manifest",
                      "status": "verified", "sealed_segments": 1}
    assert main(["--audit-path", str(audit)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "verified"
    with pytest.raises(SystemExit) as e:
        main(["--audit-path", str(audit), "--initialize", "--confirm-stopped"])
    assert e.value.code == 2  # Never silently overwrite a baseline.
    assert verify_quality_manifest(active)["sealed_segments"] == 1
    emit(audit, "document_writeback_confirmed", "WRITEBACK_CONFIRMED",
         document_id="private-key", scope="document")
    rotate_quality_event_stream(audit)
    assert verify_quality_manifest(active) == {"status": "verified", "sealed_segments": 2}
    manifest = json.loads(manifest_path(active).read_text(encoding="utf-8"))
    assert [e["sequence"] for e in manifest["segments"]] == [1, 2]
    assert set(manifest) == {"schema_version", "segments", "ledger_sha256"}
    assert "private-key" not in json.dumps(manifest)
    assert not active.exists()
    result = report_for_audit(audit)["run"]
    assert result["state"] == "observed"
    assert result["archive_integrity"]["status"] == "verified"
    assert result["metrics"]["documents_schema_pending"] == 0
    assert result["metrics"]["documents_writeback_confirmed"] == 1
    assert result["metrics"]["events"] == 3
    assert report_history(tmp_path)["selected_run_files"] == 1


def test_hash_checks_detect_same_size_in_place_edit_and_fail_closed(tmp_path):
    audit = tmp_path / "llm_call_audit_20261024-tamper.csv"
    emit(audit)
    active = quality_event_path(str(audit))
    rotate_quality_event_stream(audit)
    initialize_quality_manifest(audit)
    archive = quality_stream_segments(active)[0]
    content = archive.read_bytes()
    assert b"WORKER_LLM_TIMEOUT_EXCEPTION" in content
    archive.write_bytes(content.replace(b"TIMEOUT", b"INVALID"))  # same byte length
    with pytest.raises(ValueError, match="integrity checksum"):
        report_for_audit(audit)
    with pytest.raises(ValueError, match="integrity checksum"):
        rotate_quality_event_stream(audit)


def test_manifest_detects_missing_highest_archive_in_history(tmp_path):
    audit = tmp_path / "llm_call_audit_20261024-missing.csv"
    emit(audit)
    active = quality_event_path(str(audit))
    rotate_quality_event_stream(audit)
    initialize_quality_manifest(audit)
    quality_stream_segments(active)[0].unlink()
    with pytest.raises(ValueError, match="count differs"):
        report_for_audit(audit)
    with pytest.raises(ValueError, match="count differs"):
        report_history(tmp_path)  # Manifest-only run must not disappear.


def test_failed_manifest_publication_rolls_back_rotation_without_data_loss(tmp_path, monkeypatch):
    from czjLLM.utilities import processing_quality_manifest as mod

    audit = tmp_path / "llm_call_audit_20261024-rollback.csv"
    emit(audit)
    active = quality_event_path(str(audit))
    rotate_quality_event_stream(audit)
    initialize_quality_manifest(audit)
    old_manifest = manifest_path(active).read_bytes()
    old_archive = quality_stream_segments(active)[0].read_bytes()
    emit(audit, "stage_orchestration_failure", "STAGE_PREPARE_EXCEPTION")
    source_bytes = active.read_bytes()

    def fail_publish(*_args, **_kwargs):
        raise OSError("private-io-error")

    monkeypatch.setattr(mod, "_publish_manifest", fail_publish)
    with pytest.raises(OSError, match="private-io-error"):
        rotate_quality_event_stream(audit)
    assert active.read_bytes() == source_bytes
    assert manifest_path(active).read_bytes() == old_manifest
    assert len(quality_stream_segments(active)) == 1
    assert quality_stream_segments(active)[0].read_bytes() == old_archive


def test_corrupt_or_replaced_ledger_rejected_not_rebaselined(tmp_path):
    audit = tmp_path / "llm_call_audit_20261024-ledger.csv"
    emit(audit)
    active = quality_event_path(str(audit))
    rotate_quality_event_stream(audit)
    initialize_quality_manifest(audit)
    path = manifest_path(active)
    raw = path.read_bytes()
    path.write_bytes(raw.replace(b'"ledger_sha256":"', b'"ledger_sha256":"f', 1))
    with pytest.raises(ValueError, match="checksum|schema"):
        verify_quality_manifest(active)
    with pytest.raises(ValueError):
        initialize_quality_manifest(audit)
    assert quality_stream_segments(active)


def test_symlinked_manifest_is_rejected_and_cli_reports_no_private_paths(tmp_path, capsys):
    audit = tmp_path / "llm_call_audit_20261024-symlink.csv"
    emit(audit)
    active = quality_event_path(str(audit))
    rotate_quality_event_stream(audit)
    manifest = manifest_path(active)
    target = tmp_path / "private-manifest"
    target.write_text("private secret", encoding="utf-8")
    try:
        manifest.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink not supported")
    with pytest.raises(ValueError, match="symlink"):
        verify_quality_manifest(active)
    with pytest.raises(SystemExit) as x:
        main(["--audit-path", str(audit)])
    assert x.value.code == 2
    assert str(tmp_path) not in capsys.readouterr().err
    assert target.read_text(encoding="utf-8") == "private secret"


def test_unchanged_active_only_has_no_manifest_requirement(tmp_path):
    audit = tmp_path / "llm_call_audit_20261024-active.csv"
    emit(audit)
    result = report_for_audit(audit)["run"]
    assert result["archive_integrity"] == {
        "status": "not_applicable", "sealed_segments": 0,
    }
    assert result["metrics"]["events"] == 1
