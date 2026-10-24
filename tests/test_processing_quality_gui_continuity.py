"""Actual-file incremental GUI quality continuity across manual archival JSONL generations."""
from __future__ import annotations

import json
import queue
import threading

import pytest

from czjLLM.job_manager.win_gui import _quality_reader_worker, format_quality_summary
from czjLLM.utilities.processing_quality import (
    emit_quality_event, quality_event_path, QualityAccumulator,
)
from czjLLM.utilities.processing_quality_manifest import initialize_quality_manifest
from czjLLM.utilities.processing_quality_rotation import (
    quality_stream_segments, rotate_quality_event_stream,
)
from czjLLM.utilities.processing_quality_run_reader import QualityRunTailReader


def _emit(audit, event, code, *, doc="", scope="run"):
    emit_quality_event(str(audit), run_id="safe", event=event, code=code,
                       scope=scope, outcome="observed", document_id=doc)


def test_incremental_live_poll_and_two_rotations_keep_cumulative_events(tmp_path):
    audit = tmp_path / "llm_call_audit_20261024-gui.csv"
    active = quality_event_path(str(audit))
    reader = QualityRunTailReader(str(active))
    changed, empty = reader.poll()
    assert changed and empty["events"] == 0
    assert empty["quality_stream_status"] == "not_initialized"
    assert reader.poll()[0] is False

    _emit(audit, "document_schema_rejected", "SCHEMA_OTHER",
          scope="document", doc="sensitive-doc")
    changed, first = reader.poll()
    assert changed and first["documents_schema_pending"] == 1
    assert first["events"] == 1
    assert first["quality_stream_status"] == "observed"
    assert reader.poll()[0] is False

    # Maintenance happens between polls with producers/GUI stopped.
    rotate_quality_event_stream(audit)
    changed, archive_only = reader.poll()
    assert changed and archive_only["events"] == 1
    assert archive_only["quality_archived_segments"] == 1
    assert archive_only["quality_stream_status"] == "unsealed_legacy"
    initialize_quality_manifest(audit)
    changed, sealed = reader.poll()
    assert changed and sealed["events"] == 1
    assert sealed["quality_archive_integrity"] == "verified"

    _emit(audit, "document_writeback_confirmed", "WRITEBACK_CONFIRMED",
          scope="document", doc="sensitive-doc")
    changed, recovered = reader.poll()
    assert changed and recovered["events"] == 2
    assert recovered["documents_schema_pending"] == 0
    assert recovered["documents_writeback_confirmed"] == 1
    assert reader.poll()[0] is False

    rotate_quality_event_stream(audit)
    changed, second = reader.poll()
    assert changed and second["quality_archived_segments"] == 2
    assert second["events"] == 2
    assert second["quality_archive_integrity"] == "verified"

    _emit(audit, "worker_phase_failure", "WORKER_LLM_TIMEOUT_EXCEPTION")
    changed, new = reader.poll()
    assert changed and new["events"] == 3
    assert new["worker_phase_failure_events"] == 1
    assert new["documents_schema_pending"] == 0
    assert new["quality_archived_segments"] == 2
    assert "sensitive-doc" not in json.dumps(new)


def test_reader_detects_cross_shard_replayed_id_without_duplicate_counts(tmp_path):
    audit = tmp_path / "llm_call_audit_20261024-dedup.csv"
    active = quality_event_path(str(audit))
    _emit(audit, "worker_phase_failure", "WORKER_LLM_CONNECTION_EXCEPTION")
    first_bytes = active.read_bytes()
    rotate_quality_event_stream(audit)
    reader = QualityRunTailReader(str(active))
    assert reader.poll()[1]["events"] == 1
    active.write_bytes(first_bytes)
    changed, stats = reader.poll()
    assert changed is False  # Identical logical replay is not a new event.
    assert stats["events"] == 1
    assert stats["quality_archived_segments"] == 1
    _emit(audit, "stage_orchestration_failure", "STAGE_PREPARE_EXCEPTION")
    assert reader.poll()[1]["events"] == 2


def test_partial_live_record_becomes_counted_only_after_newline(tmp_path):
    audit = tmp_path / "llm_call_audit_20261024-partial.csv"
    active = quality_event_path(str(audit))
    _emit(audit, "worker_phase_failure", "WORKER_LLM_TIMEOUT_EXCEPTION")
    reader = QualityRunTailReader(str(active))
    assert reader.poll()[1]["events"] == 1
    with active.open("ab") as fp:
        fp.write(b'{"schema_version":1,"event_id":"temp"')
    change, interim = reader.poll()
    assert change
    assert interim["events"] == 1
    assert interim["quality_stream_status"] == "incomplete_tail"
    with active.open("ab") as fp:
        fp.write(b',"event":"worker_phase_failure","code":"WORKER_LLM_RATE_LIMIT_EXCEPTION","scope":"run"}\n')
    changed, done = reader.poll()
    assert changed and done["events"] == 2
    assert done["quality_stream_status"] == "observed"


def test_active_truncate_rewrite_rebuilds_one_accumulator_with_archived_history(tmp_path):
    audit = tmp_path / "llm_call_audit_20261024-reset.csv"
    active = quality_event_path(str(audit))
    _emit(audit, "worker_phase_failure", "WORKER_LLM_TIMEOUT_EXCEPTION")
    rotate_quality_event_stream(audit)
    _emit(audit, "stage_orchestration_failure", "STAGE_PREPARE_EXCEPTION")
    reader = QualityRunTailReader(str(active))
    assert reader.poll()[1]["events"] == 2
    _emit(audit, "producer_operational_failure", "PRODUCER_FUTURE_EXCEPTION")
    assert reader.poll()[1]["events"] == 3
    # Invalid external truncate/rewrite: do not retain stale active counters,
    # and do not lose the prior archived Worker incident.
    active.write_bytes(b"")
    changed, replaced = reader.poll()
    assert changed and replaced["events"] == 1
    assert replaced["worker_phase_failure_events"] == 1
    assert replaced["stage_orchestration_failure_events"] == 0
    _emit(audit, "worker_phase_failure", "WORKER_LLM_RATE_LIMIT_EXCEPTION")
    assert reader.poll()[1]["events"] == 2


def test_sealed_hash_change_or_missing_shard_fail_closed(tmp_path):
    audit = tmp_path / "llm_call_audit_20261024-manifest.csv"
    active = quality_event_path(str(audit))
    _emit(audit, "worker_phase_failure", "WORKER_LLM_TIMEOUT_EXCEPTION")
    rotate_quality_event_stream(audit)
    initialize_quality_manifest(audit)
    reader = QualityRunTailReader(str(active))
    assert reader.poll()[1]["quality_archive_integrity"] == "verified"
    shard = quality_stream_segments(active)[0]
    shard.write_bytes(shard.read_bytes().replace(b"TIMEOUT", b"INVALID"))
    with pytest.raises(ValueError, match="integrity"):
        reader.poll()
    # Erasure of the whole sealed shard also needs to fail, not silently zero.
    shard.unlink()
    with pytest.raises(ValueError, match="count differs"):
        reader.poll()


def test_corrupt_or_unsealed_shards_surface_explicit_warning_not_false_success(tmp_path):
    audit = tmp_path / "llm_call_audit_20261024-bad.csv"
    active = quality_event_path(str(audit))
    _emit(audit, "worker_phase_failure", "WORKER_LLM_TIMEOUT_EXCEPTION")
    rotate_quality_event_stream(audit)
    with quality_stream_segments(active)[0].open("ab") as fp:
        fp.write(b"bad-event\n")
    reader = QualityRunTailReader(str(active))
    _, stats = reader.poll()
    assert stats["events"] == 1
    assert stats["quality_stream_status"] == "degraded_corrupt_lines"
    assert stats["quality_skipped_corrupt_lines"] == 1
    assert "損毀" in format_quality_summary(stats)
    assert "未建立完整性驗證基準" in format_quality_summary({
        **stats, "quality_stream_status": "unsealed_legacy",
    })


def test_gui_background_worker_reports_validation_failure_instead_of_old_green(tmp_path):
    audit = tmp_path / "llm_call_audit_20261024-worker.csv"
    active = quality_event_path(str(audit))
    _emit(audit, "worker_phase_failure", "WORKER_LLM_CONNECTION_EXCEPTION")
    rotate_quality_event_stream(audit)
    initialize_quality_manifest(audit)
    requests = queue.Queue(maxsize=2)
    outgoing = queue.Queue(maxsize=1)
    stop = threading.Event()
    requests.put(str(active))
    worker = threading.Thread(target=_quality_reader_worker,
                              args=(requests, outgoing, stop, 0.03),
                              name="quality-gui-test", daemon=True)
    worker.start()
    try:
        observed = outgoing.get(timeout=5)
        assert observed["events"] == 1
        assert observed["quality_archive_integrity"] == "verified"
        shard = quality_stream_segments(active)[0]
        shard.write_bytes(shard.read_bytes().replace(b"CONNECTION", b"BADBADBADB"))
        invalid = outgoing.get(timeout=5)
        assert invalid["quality_stream_status"] == "unverified"
        assert invalid["events"] == 0
        assert "暫不可用" in format_quality_summary(invalid)
        assert str(tmp_path) not in json.dumps(invalid)
        assert outgoing.empty()
    finally:
        stop.set()
        worker.join(timeout=2)
    assert not worker.is_alive()


def test_path_switch_resets_prior_run_and_missing_input_is_uninitialized(tmp_path):
    audit_a = tmp_path / "llm_call_audit_20261024-a.csv"
    audit_b = tmp_path / "llm_call_audit_20261024-b.csv"
    _emit(audit_a, "worker_phase_failure", "WORKER_LLM_TIMEOUT_EXCEPTION")
    first = QualityRunTailReader(str(quality_event_path(str(audit_a))))
    assert first.poll()[1]["events"] == 1
    second = QualityRunTailReader(str(quality_event_path(str(audit_b))))
    assert second.poll()[1]["quality_stream_status"] == "not_initialized"
    _emit(audit_b, "worker_phase_failure", "WORKER_LLM_RATE_LIMIT_EXCEPTION")
    _, stats = second.poll()
    assert stats["events"] == 1
    assert stats["error_codes"] == {"WORKER_LLM_RATE_LIMIT_EXCEPTION": 1}


def test_quality_gui_wires_generation_reader_and_safe_status_display():
    from pathlib import Path
    src = Path("czjLLM/job_manager/win_gui.py").read_text(encoding="utf-8")
    assert "reader = QualityRunTailReader(path)" in src
    assert 'unavailable["quality_stream_status"] = "unverified"' in src
    assert "品質事件封存或檔案驗證異常" in src
    assert "品質事件尚無可靠統計" in src
    assert "result_queue.put_nowait(stats)" in src
