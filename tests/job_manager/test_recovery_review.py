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
    original = review.read_meter_strict
    try:
        review.read_meter_strict = lambda *_a: meter
        found = review.list_review_items("job-meter.json")
    finally:
        review.read_meter_strict = original
    assert len(found) == 1
    assert found[0]["code"] == "REVIEW_EVIDENCE_UNREADABLE"
    assert found[0]["operational"] == "unknown"
    assert run.read_bytes() == b"PRIVATE_PROMPT"


def test_writeback_failed_row_can_be_acknowledged_but_not_marked_resolved(
    tmp_path, monkeypatch
):
    item = tmp_path / "row"
    item.mkdir()
    meter = {"rows": {"r": {"item_dir": str(item),
                           "status": "writeback_failed_schema"}}}
    monkeypatch.setattr(review, "read_meter_strict", lambda *_a: meter)
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


def test_listing_paginates_beyond_500_and_prioritizes_last_failure(tmp_path):
    assert review.list_review_items() == []
    paths = [str(tmp_path / f"item_{i:04d}") for i in range(review.MAX_ITEMS)]
    problem = tmp_path / "item_9999"
    problem.mkdir()
    saved = review.read_meter_strict
    meter = {"rows": {
        str(i): {
            "item_dir": path, "status": "merged",
        } for i, path in enumerate(paths)
    }}
    meter["rows"]["9999"] = {
        "item_dir": str(problem), "status": "writeback_failed_schema",
    }
    try:
        review.read_meter_strict = lambda *_a: meter
        first = review.list_review_items("meter", with_paging=True)
        second = review.list_review_items("meter", page=1, with_paging=True)
    finally:
        review.read_meter_strict = saved
    assert first["pages"] == 2
    assert first["total_candidates"] == 501
    assert first["scanned"] == review.MAX_ITEMS
    assert any(
        record["item_dir"] == str(problem)
        and record["code"] == "writeback_failed_schema"
        for record in first["items"]
    )
    assert second["scanned"] == 1
    with pytest.raises(ValueError, match="invalid review page"):
        review.list_review_items(page_size=review.MAX_ITEMS + 1)


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


def test_new_failure_reopens_formerly_resolved_review_and_stays_visible(tmp_path):
    item, _, _ = _blocked(tmp_path)
    marker = queue.recovery_status_path(item)
    data = json.loads(marker.read_text("utf-8"))
    data.update({
        "state": "recovered", "integrity": "pending",
        "resolution": "VERIFIED_EXISTING_TODO",
    })
    marker.write_text(json.dumps(data), encoding="utf-8")
    review.set_review_action(item, "resolved")
    assert review.review_snapshot(item)["review_state"] == "resolved"
    now_failed = review.review_snapshot(item, row_status="writeback_failed")
    assert now_failed["code"] == "writeback_failed"
    assert now_failed["operational"] == "writeback_failure"
    assert now_failed["review_state"] == "open"
    assert now_failed["needs_attention"] is True
    now_incomplete = review.review_snapshot(item, row_status="recovery_incomplete")
    assert now_incomplete["code"] == "recovery_incomplete"
    assert now_incomplete["operational"] == "unknown"
    assert now_incomplete["review_state"] == "open"


def test_detailed_packet_has_timestamps_queue_roles_and_safe_correlated_calls(tmp_path):
    from czjLLM.job_manager.incident_diagnostics import build_detailed_debug_report
    from czjLLM.utilities.processing_quality import quality_event_path
    item, running, marker = _blocked(tmp_path)
    (item / "TODO").mkdir()
    (item / "Success").mkdir()
    meter = tmp_path / "meter.json"
    meter.write_text(json.dumps({
        "session_run_id": "run_123",
        "queue": {"pending": 2, "running": 1, "completed": 0},
        "progress": {"last_progress_ts": marker["first_seen_ts"]},
        "rows": {"42": {
            "item_dir": str(item), "status": "blocked_recovery",
            "queue_pending": 2, "queue_running": 1, "done": 0, "total": 3,
            "private_field": "TOP_SECRET",
        }}
    }), encoding="utf-8")
    audit = tmp_path / "llm_call_audit_debug.csv"
    audit.write_text(
        "prompt_file,model,ok,elapsed_seconds,input_tokens,output_tokens,timestamp,base_url\n"
        + f"{running},qwen3.6,NO,42.5,123,45,2026-11-01T08:00:00Z,"
          "https://user:SECRET_PASSWORD@example.com/api\n",
        encoding="utf-8",
    )
    quality = quality_event_path(str(audit))
    quality.write_text(json.dumps({
        "schema_version": 1, "scope": "run",
        "event": "worker_phase_failure",
        "code": "WORKER_LLM_TIMEOUT_EXCEPTION",
        "ts": "2026-11-01T08:01:00Z",
        "private_message": "TOP_SECRET",
    }) + "\n", encoding="utf-8")
    item_record = review.review_snapshot(item, row_status="blocked_recovery")
    record = {"item_dir": str(item), "source_row_status": "blocked_recovery",
              **item_record}
    report = build_detailed_debug_report(
        [record], meter_path=meter, audit_path=audit,
    )
    for expected in (
        "首次異常（UTC）", "TODO：存在", "RUNNING：存在", "Success：存在",
        "Queue 待處理計數：2", "工作切片總數：3",
        "qwen3.6", "elapsed_s=42.5", "in=123", "out=45",
        "WORKER_LLM_TIMEOUT_EXCEPTION", "Run 範圍", "2026-11-01T08:00:00Z",
        "該工作可證實的部分事件順序（UTC）", "寫入復原異常標記",
    ):
        assert expected in report
    for secret in ("TOP_SECRET", "SECRET_PASSWORD", str(tmp_path),
                   "run_123", "private.txt", "42\n"):
        assert secret not in report
    assert "SQL／ES 寫回回執：未直接取得" in report
    with_path = build_detailed_debug_report(
        [record], meter_path=meter, audit_path=audit, include_paths=True,
    )
    assert str(item) in with_path
    assert "TOP_SECRET" not in with_path


def test_detailed_packet_cannot_attribute_other_item_llm_calls(tmp_path):
    from czjLLM.job_manager.incident_diagnostics import build_detailed_debug_report
    one, _, _ = _blocked(tmp_path / "one")
    other_dir = tmp_path / "other" / "item"
    other_dir.mkdir(parents=True)
    audit = tmp_path / "llm_call_audit_scope.csv"
    audit.write_text(
        "prompt_file,model,ok,elapsed_seconds,input_tokens,output_tokens\n"
        + f"{other_dir / 'TODO' / 'prompt.txt'},other-model,YES,2.0,5,6\n",
        encoding="utf-8",
    )
    snapshot = {"item_dir": str(one), "code": "TODO_CONFLICT",
                "operational": "blocked", "review_state": "open"}
    result = build_detailed_debug_report([snapshot], audit_path=audit)
    assert "未找到具工作目錄關聯的 Audit 列" in result
    assert "模型呼叫對應單一 item：未證明" in result
    assert "other-model" in result  # only in run-wide aggregate, not per-item


def test_detailed_diagnostic_does_not_read_oversized_or_symlinked_audit(tmp_path):
    from czjLLM.job_manager.incident_diagnostics import build_detailed_debug_report
    item, running, _ = _blocked(tmp_path / "one")
    audit = tmp_path / "audit.csv"
    audit.write_bytes(b"X" * (2_000_001))
    snapshot = {"item_dir": str(item), "code": "TODO_CONFLICT",
                "operational": "blocked", "review_state": "open"}
    report = build_detailed_debug_report([snapshot], audit_path=audit)
    assert "超過 2MB" in report
    assert "X" * 500 not in report
    alias = tmp_path / "alias.csv"
    try:
        alias.symlink_to(audit)
    except (OSError, NotImplementedError):
        pytest.skip("symlink unsupported")
    report = build_detailed_debug_report([snapshot], audit_path=alias)
    assert "路徑不安全" in report


def test_detailed_clipboard_button_is_optin_and_not_on_tk_io_thread():
    import inspect
    from czjLLM.job_manager import recovery_review_gui, win_gui
    src = inspect.getsource(recovery_review_gui.show_recovery_review)
    assert "複製選取條目的完整除錯包" in src
    assert "含路徑、Run ID、任務 ID（敏感；預設關閉）" in src
    assert "include_local_paths = tk.BooleanVar(value=False)" in src
    assert "build_detailed_debug_report(" in src
    assert 'name="incident-diagnostic-reader", daemon=True' in src
    assert "win.clipboard_append(result)" in src
    assert "include_paths and not messagebox.askyesno(" in src
    main = inspect.getsource(win_gui._gui_proc_main)
    assert "audit_path_provider=lambda: _audit_path" in main


def test_debug_quality_event_registered_as_run_only():
    from czjLLM.utilities.processing_quality import (
        _EVENT_CODES, _EVENT_SCOPES,
    )
    assert _EVENT_SCOPES["queue_recovery"] == "run"
    assert _EVENT_CODES["queue_recovery"] == {
        "VERIFIED_EXISTING_TODO", "OPERATOR_ACTION_REQUIRED",
    }


def test_schema_failure_integer_pk_visible_after_real_meter_roundtrip(
    tmp_path, monkeypatch,
):
    """The production Row Merger must retain item_dir for integer PK=42."""
    import inspect
    from czjLLM.sql_mode.runtime import row_merger_generic, orchestrator
    from czjLLM.prompt_pipeline.runtime_support.load_meter import (
        meter_update, meter_read,
    )
    import czjLLM.sql_mode.runtime.scheduler as scheduler

    # These are the production mutators that used to mix int and str keys.
    src = inspect.getsource(row_merger_generic.row_merger_watchdog_generic)
    assert 'd["rows"].setdefault(str(_pk), {})' in src
    assert 'd["rows"].setdefault(_pk, {})' not in src
    init = inspect.getsource(orchestrator._release_terminal_fallback_merge_error)
    assert 'd["rows"].setdefault(str(_pk), {})' in init
    meter = tmp_path / "meter.json"
    item = tmp_path / "task"
    item.mkdir()
    meter.write_text(json.dumps({
        "queue": {"pending": 0, "running": 0},
        "rows": {"42": {
            "item_dir": str(item), "status": "in_progress",
            "total": 3, "done": 3,
        }}
    }), encoding="utf-8")
    meter_update(str(meter), lambda d: d["rows"].setdefault(
        str(42), {}).update({"status": "writeback_failed_schema"}))
    records = review.list_review_items(str(meter))
    assert len(records) == 1
    assert records[0]["code"] == "writeback_failed_schema"
    assert records[0]["item_dir"] == str(item)
    assert set(meter_read(str(meter))["rows"]) == {"42"}


def test_opted_in_diagnostic_includes_run_and_row_identifiers(tmp_path):
    from czjLLM.job_manager.incident_diagnostics import build_detailed_debug_report
    item, _, _ = _blocked(tmp_path)
    meter = tmp_path / "meter.json"
    meter.write_text(json.dumps({
        "session_run_id": "test-run-567",
        "run_mode": "es",
        "queue": {"pending": 1, "running": 0},
        "rows": {"42": {"item_dir": str(item), "status": "blocked_recovery"}}
    }), encoding="utf-8")
    source = {"item_dir": str(item), "code": "TODO_CONFLICT",
              "operational": "blocked", "review_state": "open"}
    safe = build_detailed_debug_report([source], meter_path=meter)
    assert "test-run-567" not in safe
    assert "任務列 ID：已隱藏／未記錄" in safe
    assert "執行模式：es" in safe
    explicit = build_detailed_debug_report([source], meter_path=meter,
                                           include_paths=True)
    assert "Run ID：test-run-567" in explicit
    assert "任務列 ID：42" in explicit
    assert str(item) in explicit


def test_legacy_audit_naive_timestamp_kept_as_local_unknown_zone(tmp_path):
    """Previous writer emitted datetime.now().isoformat() WITHOUT offset."""
    from czjLLM.job_manager.incident_diagnostics import (
        _audit_timestamp, build_detailed_debug_report,
    )
    assert _audit_timestamp("2026-11-01T16:31:42") == (
        "2026-11-01T16:31:42（本機時間，歷史紀錄未含時區）",
        "legacy_local",
    )
    assert _audit_timestamp("2026-11-01T16:31:42+08:00") == (
        "2026-11-01T16:31:42+08:00", "offset_explicit",
    )
    item, run, _ = _blocked(tmp_path)
    audit = tmp_path / "llm_call_audit_legacy.csv"
    audit.write_text(
        "prompt_file,model,ok,elapsed_seconds,input_tokens,output_tokens,timestamp\n"
        f"{run},qwen3.6,YES,19.4,100,30,2026-11-01T16:31:42\n",
        encoding="utf-8",
    )
    source = {"item_dir": str(item), "code": "TODO_CONFLICT",
              "operational": "blocked", "review_state": "open"}
    result = build_detailed_debug_report([source], audit_path=audit)
    assert "2026-11-01T16:31:42（本機時間，歷史紀錄未含時區）" in result
    assert "elapsed_s=19.4" in result
    # A legacy time with unknown timezone must NOT be placed in UTC chronology.
    chronology = result.split("該工作可證實的部分事件順序（UTC）：", 1)[-1]
    chronology = chronology.split("處理過程完整度：", 1)[0]
    assert "2026-11-01T16:31:42" not in chronology


def test_new_audit_writer_uses_explicit_timezone_offset():
    import inspect
    from czjLLM.utilities import llm_call_audit
    source = inspect.getsource(llm_call_audit.log_llm_call)
    assert 'datetime.now().astimezone().isoformat(timespec="seconds")' in source


def test_review_gui_exposes_page_navigation_and_filters_failed_rows_first():
    import inspect
    from czjLLM.job_manager import recovery_review_gui
    src = inspect.getsource(recovery_review_gui.show_recovery_review)
    assert "with_paging=True" in src
    assert "page_size=100" in src
    assert "上一頁" in src
    assert "下一頁" in src
    assert "review_page[0]" in src
