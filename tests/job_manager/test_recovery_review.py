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


def test_review_popup_keeps_polling_after_result_delivery():
    """A refresh must not leave the review window permanently busy."""
    import inspect
    from czjLLM.job_manager import recovery_review_gui
    source = inspect.getsource(recovery_review_gui.show_recovery_review)
    poll_body = source.split("    def poll():", 1)[1].split(
        "    def do_action(action):", 1
    )[0]
    assert poll_body.count("win.after(100, poll)") == 2
    assert 'status.set(f"檢閱讀取失敗' in poll_body
    assert "rows[:] = result" in poll_body



def test_chatgpt_copy_report_contains_safe_status_but_never_private_fields():
    event = {
        "item_dir": "C:/private/queue/prompt SECRET_SOURCE",
        "code": "TODO_CONFLICT",
        "operational": "blocked",
        "review_state": "ignored",
        "source_row_status": "blocked_recovery",
        "recheck_count": 3,
        "actions_count": 2,
        "needs_attention": True,
        "prompt_text": "SECRET_PROMPT",
        "api_key": "SECRET_API_KEY",
        "traceback": "SECRET_TRACE",
        "pk": "SECRET_ROW_ID",
        "password": "SECRET_PASSWORD",
    }
    result = review.format_incident_debug_report([event])
    for expected in ("TODO_CONFLICT", "blocked", "ignored",
                     "blocked_recovery", "安全復查次數：3", "條目數：1"):
        assert expected in result
    for private in ("C:/private", "SECRET_SOURCE", "SECRET_PROMPT",
                    "SECRET_API_KEY", "SECRET_TRACE", "SECRET_ROW_ID",
                    "SECRET_PASSWORD"):
        assert private not in result
    assert "不重複 SQL/ES 寫回" in result


def test_chatgpt_copy_report_unknown_values_fail_closed_and_is_bounded():
    injection = "C:/private/api-token=DO_NOT_LEAK"
    item = {
        "code": injection, "operational": injection,
        "review_state": injection, "source_row_status": injection,
        "recheck_count": injection, "actions_count": -99,
        "needs_attention": injection,
    }
    report = review.format_incident_debug_report([item])
    assert injection not in report
    assert report.count("UNKNOWN") >= 4
    assert "安全復查次數：unknown" in report
    assert "需注意：否/未知" in report
    with pytest.raises(ValueError, match="1..100"):
        review.format_incident_debug_report([])
    with pytest.raises(ValueError, match="1..100"):
        review.format_incident_debug_report([item] * 101)


def test_copy_buttons_are_bound_to_whitelisted_formatter_in_same_tk_window():
    import inspect
    from czjLLM.job_manager import recovery_review_gui
    source = inspect.getsource(recovery_review_gui.show_recovery_review)
    assert "複製選取條目（ChatGPT 除錯）" in source
    assert "複製目前顯示的異常摘要" in source
    assert "format_incident_debug_report(items)" in source
    assert "win.clipboard_clear()" in source
    assert "win.clipboard_append(report)" in source
    assert "win.update_idletasks()" in source
    assert "_copy_debug_report(visible)" in source
    assert "_copy_debug_report([item])" in source


def test_current_writeback_failure_overrides_recovered_marker_even_if_deleted(
    tmp_path,
):
    item, run, _ = _blocked(tmp_path)
    status_path = queue.recovery_status_path(item)
    record = json.loads(status_path.read_text("utf-8"))
    record.update({
        "state": "recovered", "integrity": "pending",
        "resolution": "VERIFIED_EXISTING_TODO",
    })
    status_path.write_text(json.dumps(record), encoding="utf-8")
    review.set_review_action(item, "deleted")
    row = review.review_snapshot(item, row_status="writeback_failed_schema")
    assert row["code"] == "writeback_failed_schema"
    assert row["operational"] == "writeback_failure"
    assert row["review_state"] == "deleted"
    assert row["needs_attention"] is True
    with pytest.raises(queue.QueueClaimRollbackError):
        review.set_review_action(
            item, "resolved", row_status="writeback_failed_schema",
        )
    report = review.format_incident_debug_report([row])
    assert "writeback_failed_schema" in report
    assert "writeback_failure" in report
    assert str(tmp_path) not in report
