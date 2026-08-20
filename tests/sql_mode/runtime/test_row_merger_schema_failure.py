from __future__ import annotations

import json
import queue
from pathlib import Path
from types import SimpleNamespace

import czjLLM.sql_mode.runtime.row_merger_generic as merger_module
from czjLLM.es_mode.output_profiles.multidim_event import normalize_multidim_event_payload


class _Registry:
    def __init__(self, item_dir: str, meta: dict) -> None:
        self.item_dir = item_dir
        self.meta = meta
        self.removed = False

    def list_items(self):
        return {} if self.removed else {self.item_dir: self.meta}

    def remove(self, item_dir):
        assert item_dir == self.item_dir
        self.removed = True


class _InvalidSchemaSink:
    def open(self):
        return None

    def write_main(self, pk, write_map, update_time=None):
        raise ValueError(
            "multidim_event_json[0].Event[1] contains fields not present "
            "in the current schema: ['constance']"
        )

    def close(self):
        return None


def test_constance_remains_an_invalid_schema_field():
    payload = [{
        "article_date_iso": None,
        "article_date_precision": "unknown",
        "Event": [{
            "event_id": "E1",
            "time_raw": None,
            "time_iso": None,
            "time_precision": "unknown",
            "constance": "must not be silently repaired",
        }],
    }]

    try:
        normalize_multidim_event_payload(payload)
    except ValueError as exc:
        assert "contains fields not present in the current schema: ['constance']" in str(exc)
    else:
        raise AssertionError("constance must remain visible as an invalid LLM output")


def test_schema_failure_releases_row_for_next_run(tmp_path: Path, monkeypatch):
    item_dir = tmp_path / "prompt_item"
    item_dir.mkdir()
    source_txt = tmp_path / "source.txt"
    source_txt.write_text("article", encoding="utf-8")
    combined = tmp_path / "combined.txt"
    combined.write_text(json.dumps({"result": "invalid schema"}), encoding="utf-8")

    registry = _Registry(
        str(item_dir),
        {"pk": "doc-1", "temp_txt": str(source_txt), "CombBackFN": str(combined)},
    )
    releases = []
    adjustments = []
    monkeypatch.setattr(
        merger_module,
        "mark_not_running",
        lambda ctx, pk, state: releases.append((pk, state)),
    )
    monkeypatch.setattr(
        merger_module,
        "record_adjustment",
        lambda ctx, event, pk=None, **extra: (
            adjustments.append((event, pk, extra)) or tmp_path / "schema-errors.jsonl"
        ),
    )

    done_q = queue.Queue()
    ctx = SimpleNamespace(
        output_col="multidim_event_json",
        record_update_time=False,
        flatten_json_output=False,
        row_merger_failure_log_interval=60,
    )
    merger_module.row_merger_watchdog_generic(
        ctx=ctx,
        registry=registry,
        meter_fn=lambda *_: None,
        stop_event=SimpleNamespace(is_set=lambda: True),
        sink=_InvalidSchemaSink(),
        scan_interval=0.001,
        done_q=done_q,
    )

    assert registry.removed is True
    assert releases == [("doc-1", "writeback_failed_schema")]
    assert adjustments[0][:2] == ("writeback_failed_schema_release", "doc-1")
    assert adjustments[0][2]["combined_result_path"] == str(combined)
    assert adjustments[0][2]["output_col"] == "multidim_event_json"
    assert done_q.get_nowait() == 1
    assert source_txt.exists(), "failed rows must remain pending rather than be backed up"
