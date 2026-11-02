"""Large/rotating real CSV model/IP evidence; no model/SQL/ES/Queue involved."""
from __future__ import annotations

import csv
import json
import os

import pytest

from czjLLM.job_manager import document_model_endpoint_incremental as inc
from czjLLM.job_manager.document_progress import read_document_progress


_HEADER = ("prompt_file", "model", "base_url", "ok", "error")


def _csv(path, records, *, append=False):
    with path.open("a" if append else "w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=_HEADER)
        if not append:
            writer.writeheader()
        writer.writerows(records)


def _record(item, n, ip, error=""):
    return {
        "prompt_file": str(item / "RUNNING" / f"{n}.txt"),
        "model": "qwen3.6:128k",
        "base_url": f"http://{ip}:11434/v1?token=SECRET",
        "ok": "YES", "error": error,
    }


def _until_caught_up(path, mapping, *, max_polls=40):
    history = []
    for _ in range(max_polls):
        result = inc.read_incremental_model_endpoints(path, mapping)
        history.append(result)
        if result["complete"]:
            return history
    raise AssertionError("incremental Audit never caught up")


def test_real_audit_above_original_16_mib_is_incrementally_indexed(tmp_path):
    item = tmp_path / "row"
    audit = tmp_path / "llm_call_audit_large.csv"
    # Cheap enough for Hosted CI, but above the original strict 16 MiB cap.
    error = "private-payload-" + "X" * 17000
    _csv(audit, [_record(item, n, f"10.0.0.{n % 9 + 1}", error)
                 for n in range(1050)])
    assert audit.stat().st_size > 16 * 1024 * 1024
    before = audit.stat()
    history = _until_caught_up(audit, {"doc": str(item)})
    assert len(history) > 1
    assert not history[0]["complete"]
    assert history[-1]["complete"]
    assert history[-1]["scanned_bytes"] == audit.stat().st_size
    assert history[-1]["models"]["doc"]["latest"] == "qwen3.6:128k · 10.0.0.6:11434"
    assert len(history[-1]["models"]["doc"]["pairs"]) == 6
    assert history[-1]["models"]["doc"]["more_pairs"]
    assert all("private-payload" not in json.dumps(result) for result in history)
    assert audit.stat().st_size == before.st_size


def test_incremental_append_tracks_actual_latest_across_revisit(tmp_path, monkeypatch):
    monkeypatch.setattr(inc, "MAX_SCAN_BYTES", 220)
    item = tmp_path / "row"
    audit = tmp_path / "llm_call_audit_append.csv"
    _csv(audit, [_record(item, 1, "10.1.1.1"),
                 _record(item, 2, "10.1.1.2")])
    first = _until_caught_up(audit, {"doc": str(item)})
    assert first[-1]["models"]["doc"]["latest"] == "qwen3.6:128k · 10.1.1.2:11434"
    _csv(audit, [_record(item, 3, "10.1.1.1")], append=True)
    after = _until_caught_up(audit, {"doc": str(item)})[-1]
    assert after["models"]["doc"]["latest"] == "qwen3.6:128k · 10.1.1.1:11434"
    assert len(after["models"]["doc"]["pairs"]) == 2


def test_quoted_multiline_csv_row_is_not_misparsed_or_committed_early(tmp_path, monkeypatch):
    monkeypatch.setattr(inc, "MAX_SCAN_BYTES", 230)
    item = tmp_path / "row"
    audit = tmp_path / "llm_call_audit_multiline.csv"
    _csv(audit, [_record(item, 1, "10.2.0.1", error="quoted\nmultiline\nprivate"),
                 _record(item, 2, "10.2.0.2")])
    progress = _until_caught_up(audit, {"doc": str(item)})
    assert progress[-1]["models"]["doc"]["latest"] == "qwen3.6:128k · 10.2.0.2:11434"
    assert "multiline" not in json.dumps(progress[-1])


def test_rotation_replaces_cached_document_model_evidence(tmp_path):
    item = tmp_path / "row"
    audit = tmp_path / "llm_call_audit_rotate.csv"
    _csv(audit, [_record(item, 1, "10.3.0.1")])
    assert _until_caught_up(audit, {"doc": str(item)})[-1]["models"]["doc"]["latest"].endswith("10.3.0.1:11434")
    staged = tmp_path / "new-audit.csv"
    _csv(staged, [_record(item, 2, "10.3.0.2")])
    os.replace(staged, audit)
    fresh = _until_caught_up(audit, {"doc": str(item)})[-1]
    assert fresh["models"]["doc"]["latest"].endswith("10.3.0.2:11434")
    assert len(fresh["models"]["doc"]["pairs"]) == 1


def test_discard_broken_header_oversize_and_symlink_evidence(tmp_path):
    item = tmp_path / "row"
    audit = tmp_path / "llm_call_audit_invalid.csv"
    audit.write_text("wrong,header\nPRIVATE,SECRET\n", encoding="utf-8")
    with pytest.raises(ValueError):
        inc.read_incremental_model_endpoints(audit, {"doc": str(item)})
    _csv(audit, [_record(item, 1, "10.3.0.4")])
    assert _until_caught_up(audit, {"doc": str(item)})[-1]["complete"]
    link = tmp_path / "linked.csv"
    try:
        link.symlink_to(audit)
    except (OSError, NotImplementedError):
        pass
    else:
        with pytest.raises(ValueError):
            inc.read_incremental_model_endpoints(link, {"doc": str(item)})
    too_large = tmp_path / "oversized.csv"
    with too_large.open("wb") as stream:
        stream.truncate(inc.MAX_FILE_BYTES + 1)
    with pytest.raises(ValueError):
        inc.read_incremental_model_endpoints(too_large, {"doc": str(item)})


def test_partial_scan_never_reports_stale_model_in_gui(tmp_path, monkeypatch):
    monkeypatch.setattr(inc, "MAX_SCAN_BYTES", 200)
    item = tmp_path / "row"
    meter = tmp_path / "loadmeter.json"
    meter.write_text(json.dumps({"rows": {"row": {
        "item_dir": str(item), "total": 2, "done": 1,
        "queue_running": 1, "status": "in_progress",
    }}}), encoding="utf-8")
    audit = tmp_path / "llm_call_audit_many.csv"
    _csv(audit, [_record(item, i, f"10.4.0.{i}") for i in range(1, 8)])
    first = read_document_progress(meter, audit_path=str(audit))
    assert first["shown"][0]["model_endpoint"] == "—"
    assert "增量讀取中" in first["notice"]
    assert "LLM 執行中" in first["shown"][0]["stage"]
    for _ in range(20):
        result = read_document_progress(meter, audit_path=str(audit))
        if "增量讀取中" not in result["notice"]:
            break
    assert "增量讀取中" not in result["notice"]
    assert result["shown"][0]["model_endpoint"].startswith("qwen3.6:128k · 10.4.0.7:11434")


def test_unchanged_file_refresh_does_not_rescan_from_start(tmp_path, monkeypatch):
    item = tmp_path / "row"
    audit = tmp_path / "llm_call_audit_stable.csv"
    _csv(audit, [_record(item, 1, "10.5.0.5")])
    original = inc._consume_csv
    calls = []
    def counted(state, chunk, mapping):
        calls.append(len(chunk))
        return original(state, chunk, mapping)
    monkeypatch.setattr(inc, "_consume_csv", counted)
    a = _until_caught_up(audit, {"doc": str(item)})[-1]
    b = inc.read_incremental_model_endpoints(audit, {"doc": str(item)})
    assert a["models"] == b["models"]
    assert calls[-1] == 0
    assert b["complete"]
