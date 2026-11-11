"""Real temporary Meter files; no LLM, Queue mutation, or production sink."""
import json
from pathlib import Path

import pytest

from czjLLM.job_manager.queue_receipt_inventory import summarize_meter
from scripts.inspect_queue_receipts import collect, human_summary, main


def _meter(*, queue_running=0, rows=None):
    return {
        "queue": {"pending": 0, "running": queue_running, "completed": 5},
        "session_run_id": "PRIVATE_RUN_2026",
        "rows": rows if rows is not None else {},
    }


def test_terminal_ghost_receipts_counted_without_private_identifiers():
    meter = _meter(queue_running=33, rows={
        "PRIVATE_PK_A": {"status": "merged", "queue_pending": 0,
                         "queue_running": 19, "item_dir": "/private/pathA"},
        "PRIVATE_PK_B": {"status": "writeback_failed_schema", "queue_pending": 0,
                         "queue_running": 13, "item_dir": "/private/pathB"},
        "PRIVATE_PK_C": {"status": "in_progress", "queue_pending": 0,
                         "queue_running": 1},
        "PRIVATE_PK_D": {"status": "merged", "queue_pending": 0,
                         "queue_running": 0},
    })
    result = summarize_meter(meter)
    counts = result["row_receipts"]
    assert result["status"] == "REVIEW_REQUIRED"
    assert counts["total_rows"] == 4
    assert counts["terminal_rows_with_outstanding_receipts"] == 2
    assert counts["terminal_running_receipts"] == 32
    assert counts["outstanding_rows"] == 3
    assert counts["settled_rows"] == 1
    assert result["queue"]["running"] == 33
    for forbidden in ("PRIVATE_", "/private/", "2026", "pathA"):
        assert forbidden not in json.dumps(result)


@pytest.mark.parametrize("row", [
    {}, {"status": "merged", "queue_running": False, "queue_pending": 0},
    {"status": "merged", "queue_running": -1, "queue_pending": 0},
    {"status": "merged", "queue_running": "0", "queue_pending": 0},
    {"status": "merged", "queue_running": 0, "queue_pending": None},
    None,
])
def test_unknown_receipts_never_become_zero(row):
    report = summarize_meter(_meter(rows={"PRIVATE_ROW": row}))
    assert report["status"] == "INCOMPLETE_EVIDENCE"
    assert report["row_receipts"]["unknown_receipt_rows"] == 1
    assert report["row_receipts"]["settled_rows"] == 0


def test_global_running_without_valid_row_receipt_is_only_a_review_signal():
    report = summarize_meter(_meter(queue_running=19, rows={
        "PRIVATE_ROW": {"status": "merged", "queue_running": 0, "queue_pending": 0},
    }))
    assert report["status"] == "REVIEW_REQUIRED"
    assert "GLOBAL_RUNNING_WITHOUT_OBSERVED_ROW_RUNNING" in report["signals"]
    assert report["gpu_utilization"] == "NOT_MEASURED"
    assert report["sink_readback"] == "NOT_MEASURED"


@pytest.mark.parametrize("bad", [
    {}, {"queue": {}, "rows": []}, {"queue": [], "rows": {}}, None,
])
def test_invalid_structure_fails_closed(bad):
    with pytest.raises(ValueError):
        summarize_meter(bad)


def test_invalid_global_counts_never_default_to_zero():
    report = summarize_meter({
        "queue": {"pending": False, "running": -1, "completed": "0"},
        "rows": {"pk": {"status": "merged", "queue_pending": 0,
                        "queue_running": 0}},
    })
    assert report["status"] == "INCOMPLETE_EVIDENCE"
    assert report["queue"] == {
        "pending": None, "running": None, "completed": None,
    }


def test_explicit_meter_cli_is_readonly_and_redacted(tmp_path, capsys):
    path = tmp_path / "PRIVATE_directory" / "loadmeter_PRIVATE.json"
    path.parent.mkdir()
    before = _meter(queue_running=13, rows={
        "PRIVATE_PK": {"status": "merged", "queue_pending": 0,
                       "queue_running": 13, "item_dir": "PRIVATE_PATH"},
    })
    path.write_text(json.dumps(before), encoding="utf-8")
    content_before = path.read_bytes()
    assert main(["--meter-file", str(path)]) == 2
    payload = capsys.readouterr().out
    report = json.loads(payload)
    assert report["status"] == "REVIEW_REQUIRED"
    assert "PRIVATE" not in payload and str(path) not in payload
    assert path.read_bytes() == content_before
    assert main(["--meter-file", str(path), "--human"]) == 2
    chinese = capsys.readouterr().out
    assert "已標終態但收據未歸零：1 列" in chinese
    assert "PRIVATE" not in chinese and str(path) not in chinese
    assert path.read_bytes() == content_before


def test_empty_parsable_snapshot_does_not_claim_success(tmp_path, capsys):
    path = tmp_path / "meter.json"
    path.write_text(json.dumps(_meter()), encoding="utf-8")
    assert main(["--meter-file", str(path)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "OBSERVED_NOT_PROVEN"
    assert output["sink_readback"] == "NOT_MEASURED"


def test_missing_corrupt_and_oversize_are_unavailable(tmp_path, capsys):
    path = tmp_path / "PRIVATE_meter.json"
    for content in (None, b'{"rows":', b"x" * (12 * 1024 * 1024 + 1)):
        if content is not None:
            path.write_bytes(content)
        report = collect(path)
        assert report["status"] == "UNAVAILABLE"
        assert "PRIVATE" not in json.dumps(report)
    assert main(["--meter-file", str(path), "--human"]) == 2
    assert "PRIVATE" not in capsys.readouterr().out


def test_symlink_meter_or_parent_is_rejected(tmp_path):
    hidden = tmp_path / "PRIVATE_hidden"
    hidden.mkdir()
    file = hidden / "meter.json"
    file.write_text(json.dumps(_meter()), encoding="utf-8")
    link = tmp_path / "link"
    try:
        link.symlink_to(hidden, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    assert collect(link / "meter.json")["status"] == "UNAVAILABLE"
    assert collect(file)["status"] == "OBSERVED_NOT_PROVEN"


def test_changed_file_during_collection_is_not_silently_accepted(tmp_path, monkeypatch):
    import scripts.inspect_queue_receipts as module
    path = tmp_path / "meter.json"
    initial = _meter()
    path.write_text(json.dumps(initial), encoding="utf-8")

    def changed(_path):
        path.write_text(json.dumps(_meter(queue_running=19)), encoding="utf-8")
        return initial

    monkeypatch.setattr(module, "read_meter_strict", changed)
    assert collect(path)["status"] == "UNAVAILABLE"


def test_large_but_bounded_row_projection():
    rows = {
        "PRIVATE_" + str(i): {"status": "merged", "queue_pending": 0,
                             "queue_running": 0}
        for i in range(35_385)
    }
    report = summarize_meter(_meter(rows=rows))
    assert report["row_receipts"]["total_rows"] == 35_385
    assert report["row_receipts"]["settled_rows"] == 35_385
    assert report["status"] == "OBSERVED_NOT_PROVEN"
    assert "PRIVATE_" not in json.dumps(report)


def test_cli_help_requires_explicit_meter(capsys):
    with pytest.raises(SystemExit) as stopped:
        main(["--help"])
    assert stopped.value.code == 0
    output = capsys.readouterr().out
    assert "--meter-file" in output
    assert "--human" in output
