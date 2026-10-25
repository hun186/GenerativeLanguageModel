"""Physical JSONL/GUI tests for budgeted cumulative quality snapshots.

Budgets are GUI-only safety thresholds, not pruning or approximations.
Normal offline QualityAccumulator/QualityTailReader remain uncapped.
"""
from __future__ import annotations

import json
import queue
import threading

import pytest

from czjLLM.job_manager import win_gui
from czjLLM.utilities.processing_quality import (
    QualityAccumulator,
    QualityCapacityExceeded,
    QualityTailReader,
    emit_quality_event,
    quality_event_path,
)
from czjLLM.utilities.processing_quality_rotation import rotate_quality_event_stream
from czjLLM.utilities.processing_quality_run_reader import QualityRunTailReader


def _emit(audit, *, code="WORKER_LLM_TIMEOUT_EXCEPTION"):
    return emit_quality_event(
        str(audit), run_id="safe", event="worker_phase_failure",
        code=code, scope="run", outcome="observed",
    )


def test_retention_budget_is_opt_in_and_rejects_before_any_mutation():
    record = {
        "schema_version": 1, "event_id": "one",
        "event": "worker_phase_failure", "code": "WORKER_LLM_TIMEOUT_EXCEPTION",
        "scope": "run",
    }
    other = {**record, "event_id": "two"}
    acc = QualityAccumulator(max_events=1)
    assert acc.add(record)
    baseline = acc.snapshot()
    assert not acc.add(record)
    assert acc.snapshot() == baseline
    with pytest.raises(QualityCapacityExceeded, match="unique event"):
        acc.add(other)
    assert acc.snapshot() == baseline
    # Existing offline report is deliberately unaffected.
    unlimited = QualityAccumulator()
    assert unlimited.add(record) and unlimited.add(other)
    assert unlimited.snapshot()["events"] == 2
    for kw in ({"max_events": 0}, {"max_events": True},
               {"max_identity_chars": -1}, {"max_identity_chars": False}):
        with pytest.raises(ValueError):
            QualityAccumulator(**kw)


def test_retained_identity_budget_rejects_before_mutation():
    record = {
        "schema_version": 1, "event_id": "event-one",
        "event": "document_schema_rejected", "code": "SCHEMA_OTHER",
        "scope": "document", "document_id": "document-1",
    }
    acc = QualityAccumulator(max_identity_chars=21)  # 9 + 10 + small margin
    assert acc.add(record)
    before = acc.snapshot()
    with pytest.raises(QualityCapacityExceeded, match="identity"):
        acc.add({**record, "event_id": "event-two"})
    assert acc.snapshot() == before
    copy = acc.empty_copy()
    assert copy.snapshot()["events"] == 0
    assert copy.add(record)


def test_active_budget_never_advances_offset_past_rejected_event(tmp_path):
    audit = tmp_path / "llm_call_audit_20261025-limit.csv"
    active = quality_event_path(str(audit))
    _emit(audit)
    first_size = active.stat().st_size
    reader = QualityTailReader(
        str(active), accumulator=QualityAccumulator(max_events=1),
        max_line_bytes=4096,
    )
    assert reader.poll()[1]["events"] == 1
    assert reader.offset == first_size
    _emit(audit, code="WORKER_LLM_CONNECTION_EXCEPTION")
    for _ in range(3):
        with pytest.raises(QualityCapacityExceeded, match="event budget"):
            reader.poll()
        assert reader.offset == first_size
        assert reader.accumulator.snapshot()["events"] == 1


def test_one_overlong_line_fails_closed_without_parsing_or_losing_offset(tmp_path):
    audit = tmp_path / "llm_call_audit_20261025-longline.csv"
    active = quality_event_path(str(audit))
    _emit(audit)
    first_size = active.stat().st_size
    reader = QualityTailReader(
        str(active), accumulator=QualityAccumulator(max_events=3),
        max_line_bytes=4096,
    )
    assert reader.poll()[1]["events"] == 1
    with active.open("ab") as fp:
        fp.write(b'{"schema_version":1,"event_id":"' + b"A" * 4500 + b'"}\n')
    for _ in range(2):
        with pytest.raises(QualityCapacityExceeded, match="line budget"):
            reader.poll()
        assert reader.offset == first_size
    # The original raw event remains untouched, and the uncapped parser may
    # evaluate it under existing validation/error semantics.
    assert active.read_bytes().startswith(b'{"schema_version"')


def test_run_reader_budget_counts_archived_and_active_records_together(tmp_path):
    audit = tmp_path / "llm_call_audit_20261025-shards.csv"
    active = quality_event_path(str(audit))
    _emit(audit)
    rotate_quality_event_stream(audit)
    reader = QualityRunTailReader(
        str(active), max_events=1, max_identity_chars=1000,
        max_line_bytes=4096,
    )
    assert reader.poll()[1]["events"] == 1
    _emit(audit, code="WORKER_LLM_CONNECTION_EXCEPTION")
    for _ in range(2):
        with pytest.raises(QualityCapacityExceeded):
            reader.poll()
    assert active.exists()
    assert list(active.parent.glob(active.name + ".seg-*"))


def test_archive_initial_replay_above_budget_never_returns_partial_snapshot(tmp_path):
    audit = tmp_path / "llm_call_audit_20261025-backlog.csv"
    active = quality_event_path(str(audit))
    _emit(audit)
    _emit(audit, code="WORKER_LLM_CONNECTION_EXCEPTION")
    rotate_quality_event_stream(audit)
    reader = QualityRunTailReader(
        str(active), max_events=1, max_identity_chars=1000,
        max_line_bytes=4096,
    )
    with pytest.raises(QualityCapacityExceeded):
        reader.poll()
    assert reader._accumulator.snapshot()["events"] == 0
    # No successful partial result may be cached.
    assert reader._last_report is None


def test_gui_thread_surfaces_budget_exceeded_and_can_switch_runs(tmp_path, monkeypatch):
    audit_a = tmp_path / "llm_call_audit_20261025-gui-large.csv"
    audit_b = tmp_path / "llm_call_audit_20261025-gui-small.csv"
    _emit(audit_a)
    _emit(audit_b)
    real = QualityRunTailReader
    monkeypatch.setattr(
        win_gui, "QualityRunTailReader",
        lambda path="": real(path, max_events=1, max_identity_chars=1000,
                             max_line_bytes=4096),
    )
    requests = queue.Queue(maxsize=2)
    outgoing = queue.Queue(maxsize=1)
    stop = threading.Event()
    requests.put(str(quality_event_path(str(audit_a))))
    worker = threading.Thread(
        target=win_gui._quality_reader_worker,
        args=(requests, outgoing, stop, 0.03), name="quality-budget-test",
        daemon=True,
    )
    worker.start()
    try:
        first = outgoing.get(timeout=5)
        assert first["quality_stream_status"] == "observed"
        assert first["events"] == 1
        _emit(audit_a, code="WORKER_LLM_CONNECTION_EXCEPTION")
        exceeded = outgoing.get(timeout=5)
        assert exceeded["quality_stream_status"] == "capacity_exceeded"
        assert exceeded["events"] == 0
        assert "安全累計上限" in win_gui.format_quality_summary(exceeded)
        assert str(tmp_path) not in json.dumps(exceeded)
        assert quality_event_path(str(audit_a)).exists()
        requests.put(str(quality_event_path(str(audit_b))))
        recovered = outgoing.get(timeout=5)
        assert recovered["quality_stream_status"] == "observed"
        assert recovered["events"] == 1
    finally:
        stop.set()
        worker.join(timeout=2)
    assert not worker.is_alive()


def test_run_reader_budget_validation_rejects_boolean_and_zero():
    for opts in ({"max_events": 0}, {"max_events": True},
                 {"max_identity_chars": False}, {"max_line_bytes": 0}):
        with pytest.raises(ValueError):
            QualityRunTailReader("any", **opts)
    with pytest.raises(ValueError):
        QualityTailReader("any", max_line_bytes=True)


def test_gui_status_label_and_cap_bounds_wired():
    from pathlib import Path

    code = Path("czjLLM/job_manager/win_gui.py").read_text(encoding="utf-8")
    assert "except QualityCapacityExceeded:" in code
    assert 'unavailable["quality_stream_status"] = "capacity_exceeded"' in code
    assert '"capacity_exceeded"' in code
    assert QualityRunTailReader.DEFAULT_MAX_EVENTS == 50_000
    assert QualityRunTailReader.DEFAULT_MAX_LINE_BYTES == 64 * 1024


def test_stable_overbudget_sealed_archive_does_not_replay_or_rehash(tmp_path, monkeypatch):
    """Codex P2: stable oversized runs must stay unavailable at constant poll cost."""
    import czjLLM.utilities.processing_quality_run_reader as reader_module
    from czjLLM.utilities.processing_quality_manifest import initialize_quality_manifest

    audit = tmp_path / "llm_call_audit_20261025-cache-sealed.csv"
    active = quality_event_path(str(audit))
    _emit(audit)
    _emit(audit, code="WORKER_LLM_CONNECTION_EXCEPTION")
    rotate_quality_event_stream(audit)
    initialize_quality_manifest(audit)

    calls = {"add": 0, "verify": 0}
    real_add = QualityAccumulator.add
    real_verify = reader_module.verify_quality_manifest

    def count_add(acc, record):
        calls["add"] += 1
        return real_add(acc, record)

    def count_verify(*args, **kwargs):
        calls["verify"] += 1
        return real_verify(*args, **kwargs)

    monkeypatch.setattr(QualityAccumulator, "add", count_add)
    monkeypatch.setattr(reader_module, "verify_quality_manifest", count_verify)
    reader = QualityRunTailReader(
        str(active), max_events=1, max_identity_chars=1000,
        max_line_bytes=4096,
    )
    with pytest.raises(QualityCapacityExceeded):
        reader.poll()
    initial = dict(calls)
    assert initial["add"] == 2 and initial["verify"] >= 1
    for _ in range(4):
        with pytest.raises(QualityCapacityExceeded, match="remains over budget"):
            reader.poll()
    assert calls == initial  # no repeated replay or SHA256 verification
    assert reader._last_report is None
    assert reader._accumulator.snapshot()["events"] == 0
    # Changing active file generation forces exactly one new attempt, then
    # its new generation also stays cached while source metadata is stable.
    _emit(audit)
    with pytest.raises(QualityCapacityExceeded):
        reader.poll()
    assert calls["add"] > initial["add"]
    revised = dict(calls)
    with pytest.raises(QualityCapacityExceeded, match="remains over budget"):
        reader.poll()
    assert calls == revised


def test_cached_overbudget_active_file_can_recover_after_rewrite(tmp_path, monkeypatch):
    audit = tmp_path / "llm_call_audit_20261025-cache-recover.csv"
    active = quality_event_path(str(audit))
    _emit(audit)
    one_event = active.read_bytes()
    _emit(audit, code="WORKER_LLM_CONNECTION_EXCEPTION")
    calls = {"add": 0}
    real_add = QualityAccumulator.add

    def count_add(acc, record):
        calls["add"] += 1
        return real_add(acc, record)

    monkeypatch.setattr(QualityAccumulator, "add", count_add)
    reader = QualityRunTailReader(
        str(active), max_events=1, max_identity_chars=1000,
        max_line_bytes=4096,
    )
    with pytest.raises(QualityCapacityExceeded):
        reader.poll()
    n = calls["add"]
    for _ in range(2):
        with pytest.raises(QualityCapacityExceeded):
            reader.poll()
    assert calls["add"] == n
    # Maintenance-only replacement of this unsealed fixture creates a new
    # metadata generation; successful stats must then be re-published.
    active.write_bytes(one_event)
    changed, result = reader.poll()
    assert changed and result["quality_stream_status"] == "observed"
    assert result["events"] == 1
    assert calls["add"] > n
    assert reader.poll()[0] is False


def test_cached_capacity_failure_cannot_hide_removed_legacy_archive(tmp_path):
    audit = tmp_path / "llm_call_audit_20261025-cache-loss.csv"
    active = quality_event_path(str(audit))
    _emit(audit)
    rotate_quality_event_stream(audit)
    _emit(audit, code="WORKER_LLM_CONNECTION_EXCEPTION")
    rotate_quality_event_stream(audit)
    reader = QualityRunTailReader(
        str(active), max_events=1, max_identity_chars=1000,
        max_line_bytes=4096,
    )
    with pytest.raises(QualityCapacityExceeded):
        reader.poll()
    segments = list(active.parent.glob(active.name + ".seg-*"))
    assert len(segments) == 2
    last_segment = max(segments)
    backup = tmp_path / "separate-backup"
    last_segment.rename(backup)
    try:
        with pytest.raises(ValueError, match="known quality archive shard disappeared"):
            reader.poll()
    finally:
        backup.rename(last_segment)
    with pytest.raises(QualityCapacityExceeded, match="remains over budget"):
        reader.poll()
