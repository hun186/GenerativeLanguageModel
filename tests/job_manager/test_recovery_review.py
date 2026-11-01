"""No-Tk-display operator review regression suite.

Actions must never mutate the authoritative recovery file, TODO, RUNNING,
Success or downstream SQL/ES. Includes static shared-GUI dispatch contract.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from czjLLM.job_manager import recovery_review as review
from czjLLM.job_manager import win_gui
from czjLLM.prompt_pipeline.runtime_support import prompt_queue as queue


def _blocked(tmp_path):
    item = tmp_path / "job"
    run = item / "RUNNING" / "private.txt"
    run.parent.mkdir(parents=True)
    run.write_bytes(b"PRIVATE_PROMPT")
    marker = queue.mark_recovery_blocked(item, "TODO_CONFLICT", 1)
    return item, run, marker


def test_review_records_ignored_hidden_reopen_without_modifying_queue(tmp_path):
    item, run, marker = _blocked(tmp_path)
    original_status = queue.recovery_status_path(item).read_bytes()
    assert review.review_snapshot(item)["review_state"] == "open"
    for action in ("ignored", "deleted", "open"):
        result = review.set_review_action(item, action)
        assert result["action"] == action
        assert result["queue_modified"] is False
        snapshot = review.review_snapshot(item)
        assert snapshot["review_state"] == action
        assert snapshot["operational"] == "blocked"
        assert snapshot["needs_attention"] is True
        assert run.read_bytes() == b"PRIVATE_PROMPT"
        assert queue.recovery_status_path(item).read_bytes() == original_status
    history = (item / "_extract_slice_identity" / review.LOG_NAME).read_text()
    assert len(history.splitlines()) == 3
    assert "PRIVATE_PROMPT" not in history
    assert str(tmp_path) not in history
    assert "private.txt" not in history


def test_resolved_button_rejects_active_blocked_queue(tmp_path):
    item, run, _ = _blocked(tmp_path)
    with pytest.raises(queue.QueueClaimRollbackError, match="cannot mark"):
        review.set_review_action(item, "resolved")
    assert queue.read_recovery_status(item)["state"] == "blocked"
    assert run.exists()
    assert not (item / "_extract_slice_identity" / review.LOG_NAME).exists()


def test_resolved_review_does_not_claim_llm_writeback_success(tmp_path):
    item, run, _ = _blocked(tmp_path)
    status_path = queue.recovery_status_path(item)
    record = json.loads(status_path.read_text("utf-8"))
    record.update({
        "state": "recovered", "integrity": "pending",
        "resolution": "VERIFIED_EXISTING_TODO",
    })
    status_path.write_text(json.dumps(record), encoding="utf-8")
    before = status_path.read_bytes()
    event = review.set_review_action(item, "resolved")
    assert event["operational_at_review"] == "pending"
    assert review.review_snapshot(item)["review_state"] == "resolved"
    assert status_path.read_bytes() == before
    assert run.read_bytes() == b"PRIVATE_PROMPT"
    # GUI review status is not physical completion: LLM and sinks still pending.


def test_malformed_marker_is_not_silently_resolved(tmp_path):
    item, run, _ = _blocked(tmp_path)
    queue.recovery_status_path(item).write_text("{invalid", encoding="utf-8")
    with pytest.raises(queue.QueueClaimRollbackError):
        review.set_review_action(item, "resolved")
    meter = {"rows": {"x": {"item_dir": str(item), "status": "blocked_recovery"}}}
    from czjLLM.prompt_pipeline.runtime_support import load_meter
    original = load_meter.meter_read
    try:
        load_meter.meter_read = lambda *_a: meter
        found = review.list_review_items("job-meter.json")
    finally:
        load_meter.meter_read = original
    assert len(found) == 1
    assert found[0]["code"] == "REVIEW_EVIDENCE_UNREADABLE"
    assert found[0]["operational"] == "unknown"
    assert run.read_bytes() == b"PRIVATE_PROMPT"


def test_writeback_failed_row_can_be_acknowledged_but_not_marked_resolved(
    tmp_path, monkeypatch
):
    item = tmp_path / "row"
    item.mkdir()
    from czjLLM.prompt_pipeline.runtime_support import load_meter
    meter = {"rows": {"r": {"item_dir": str(item),
                           "status": "writeback_failed_schema"}}}
    monkeypatch.setattr(load_meter, "meter_read", lambda *_a: meter)
    found = review.list_review_items("current-run-meter")
    assert len(found) == 1
    assert found[0]["operational"] == "writeback_failure"
    assert found[0]["code"] == "writeback_failed_schema"
    with pytest.raises(queue.QueueClaimRollbackError):
        review.set_review_action(
            item, "resolved", row_status="writeback_failed_schema",
        )
    review.set_review_action(
        item, "ignored", row_status="writeback_failed_schema",
    )
    assert review.list_review_items("current-run-meter")[0]["review_state"] == "ignored"
    # Even after a separate worker clears its status, audit remains visible.
    meter["rows"]["r"]["status"] = "in_progress"
    later = review.list_review_items("current-run-meter")
    assert len(later) == 1
    assert later[0]["code"] == "writeback_failed_schema"


def test_gui_events_and_button_are_shared_across_one_run_gui(monkeypatch):
    import inspect
    import queue as in_memory_queue

    q = in_memory_queue.Queue()
    client = win_gui._GUIClient(
        q, SimpleNamespace(is_alive=lambda: False),
    )
    client.set_recovery_meter_path("C:/runs/selected/meter.json")
    event, path = q.get_nowait()
    assert event == win_gui._GuiEvents.RECOVERY_METER
    assert path == "C:/runs/selected/meter.json"
    source = inspect.getsource(win_gui._gui_proc_main)
    assert "重大異常檢閱／管理" in source
    assert "show_recovery_review" in source
    assert "_GuiEvents.RECOVERY_METER" in source


def test_review_rejects_symlinked_item_ancestor(tmp_path):
    item, run, _ = _blocked(tmp_path / "outside")
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(item.parent, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink unsupported")
    with pytest.raises(queue.QueueClaimRollbackError):
        review.set_review_action(alias / item.name, "ignored")
    assert run.read_bytes() == b"PRIVATE_PROMPT"


def test_listing_has_explicit_scope_and_item_limit(tmp_path):
    assert review.list_review_items() == []
    with pytest.raises(ValueError, match="limit"):
        review.list_review_items(extra_item_dirs=[
            str(tmp_path / str(i)) for i in range(review.MAX_ITEMS + 1)
        ])
