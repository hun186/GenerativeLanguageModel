"""Per-document Windows GUI projection; no display/server required."""
import inspect
import json
from types import SimpleNamespace
import pytest

from czjLLM.job_manager import document_progress as dp
from czjLLM.job_manager import win_gui


def test_item_row_statuses_distinguish_llm_slices_from_writeback():
    cases = [
        ("processing", {"status": "in_progress", "total": 10, "done": 5,
                        "queue_pending": 3, "queue_running": 2},
         "LLM 執行中", "▰▰▰▰▰▱▱▱▱▱ 50% (5/10)"),
        ("queue", {"status": "in_progress", "total": 10, "done": 5,
                   "queue_pending": 5, "queue_running": 0},
         "切片等待中", "50%"),
        ("all_slices", {"status": "in_progress", "total": 10, "done": 10,
                        "queue_pending": 0, "queue_running": 0},
         "切片完成；待合併／寫回", "100%"),
        ("writeback", {"status": "ready_for_writeback", "total": 10, "done": 10},
         "待寫回", "100%"),
        ("merged", {"status": "merged", "total": 10, "done": 10},
         "Row Merger 已標 merged", "100%"),
        ("bad", {"status": "writeback_failed_schema", "total": 10, "done": 10},
         "寫回結構異常", "100%"),
        ("unknown", {"status": "in_progress", "total": None, "done": None},
         "處理中／狀態未細分", "未記錄"),
    ]
    for key, row, stage, progress in cases:
        result = dp.classify_row(key, row)
        assert result["stage"] == stage
        assert progress in result["progress"]
    assert dp.classify_row("bad", cases[5][1])["error"]
    assert not dp.classify_row("merged", cases[4][1])["active"]
    assert dp.classify_row("unknown", cases[6][1])["active"]


def test_large_run_page_priority_filter_and_no_eager_widget_per_item():
    rows = {str(i): {
        "status": "merged", "total": 1, "done": 1,
    } for i in range(6000)}
    rows["9876"] = {
        "status": "writeback_failed_schema", "total": 3, "done": 3,
    }
    rows["9001"] = {
        "status": "in_progress", "queue_running": 1,
        "queue_pending": 0, "total": 8, "done": 1,
    }
    report = dp.project_meter({"rows": rows})
    assert report["all"] == 6002
    assert report["matching"] == 2
    assert report["errors"] == 1
    assert report["active"] >= 1
    assert [x["key"] for x in report["shown"]] == ["9876", "9001"]
    everyone = dp.project_meter({"rows": rows}, mode="全部", page=2)
    assert everyone["all"] == 6002
    assert everyone["matching"] == 6002
    assert everyone["page"] == 2
    assert len(everyone["shown"]) == dp.PAGE_SIZE
    errs = dp.project_meter({"rows": rows}, mode="異常")
    assert [x["key"] for x in errs["shown"]] == ["9876"]
    needle = dp.project_meter({"rows": rows}, mode="全部", search="9001")
    assert [x["key"] for x in needle["shown"]] == ["9001"]


def test_unknown_and_bad_values_cannot_be_construed_as_success():
    row = dp.classify_row("private\nrow", {
        "status": "madeup-success", "total": "broken",
        "done": -2, "queue_running": "bad",
        "last_state_at": "no timestamp",
    })
    assert "?" in row["label"] and "\n" not in row["label"]
    assert row["stage"] == "未記錄／未知狀態"
    assert row["progress"].startswith("—")
    assert row["updated_text"] == "—"
    with pytest.raises(ValueError):
        dp.project_meter({}, mode="abnormal")
    with pytest.raises(ValueError):
        dp.project_meter({}, page=-1)


def test_safe_meter_read_bounded_and_no_silent_partial_success(tmp_path):
    path = tmp_path / "meter.json"
    from czjLLM.prompt_pipeline.runtime_support.load_meter import meter_read
    path.write_text(json.dumps({
        "rows": {"42": {
            "status": "in_progress", "total": 4, "done": 2,
            "queue_running": 1, "queue_pending": 1,
            "last_state_at": 1793500000,
        }}
    }))
    view = dp.read_document_progress(path)
    assert view["shown"][0]["label"] == "42"
    assert "50% (2/4)" in view["shown"][0]["progress"]
    assert view["shown"][0]["updated_text"] != "—"
    path.write_bytes(b"x" * (dp.MAX_METER_BYTES + 1))
    with pytest.raises(ValueError, match="unsafe or exceeds"):
        dp.read_document_progress(path)
    link = tmp_path / "alias"
    try:
        link.symlink_to(path)
    except (OSError, NotImplementedError):
        pytest.skip("link unsupported")
    with pytest.raises(ValueError, match="unsafe"):
        dp.read_document_progress(link)


def test_collapsible_gui_reads_off_tk_thread_only_while_expanded():
    source = inspect.getsource(win_gui._gui_proc_main)
    assert '▶' in source and "▼" in source
    assert "各列／文件進度" in source
    assert "document_frame.pack_forget()" in source
    assert "document_frame.pack(fill=\"x\")" in source
    assert 'name="row-progress-meter-reader"' in source
    assert "if not _document_expanded or _document_busy:" in source
    assert "root.after(250, _document_results_poll)" in source
    assert 'values=("目前處理", "異常", "全部")' in source
    assert 'page_size=page_size' not in source  # library default 12 rows
    assert 'item["updated_text"]' in source
    assert "切片100%≠寫回完成" in source
    assert 'document_previous.configure(' in source
    assert 'document_next.configure(' in source
    assert "def _document_page_delta(delta)" in source
    assert "_recovery_meter_path" in source
