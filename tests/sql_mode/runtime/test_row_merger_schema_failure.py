from __future__ import annotations

import json
import queue
from pathlib import Path
from types import SimpleNamespace

import pytest

import czjLLM.sql_mode.runtime.row_merger_generic as merger_module
from czjLLM.es_mode.output_profiles import OutputProfileValidationError
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
        raise OutputProfileValidationError(
            "multidim_event",
            "multidim_event_json[0].Event[1] contains fields not present "
            "in the current schema: ['constance']"
        )

    def close(self):
        return None


class _RetryOnceSink:
    def __init__(self):
        self.calls = 0
        self.write_maps = []

    def open(self):
        return None

    def write_main(self, pk, write_map, update_time=None):
        self.calls += 1
        self.write_maps.append(dict(write_map))
        if self.calls == 1:
            raise RuntimeError("temporary ES failure")

    def close(self):
        return None


class _CaptureMultidimSink:
    def __init__(self):
        self.write_maps = []

    def open(self):
        return None

    def write_main(self, pk, write_map, update_time=None):
        normalize_multidim_event_payload(json.loads(write_map["multidim_event_json"]))
        self.write_maps.append(dict(write_map))

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


def test_all_multidim_profile_validation_errors_are_terminal():
    for message in (
        "multidim_event_json[3].Event is required by the current schema",
        "multidim_event_json[0].Event_Timeline[0]: month precision requires normalized day 01",
    ):
        exc = OutputProfileValidationError("multidim_event", message)
        assert merger_module._is_terminal_schema_writeback_error(exc)


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


def test_slice_conflict_audit_is_logged_once_across_writeback_retry(tmp_path: Path, monkeypatch):
    item_dir = tmp_path / "prompt_item"
    item_dir.mkdir()
    source_txt = tmp_path / "source.txt"
    source_txt.write_text("article", encoding="utf-8")
    combined = tmp_path / "combined.txt"
    combined.write_text(json.dumps([{"score": 85}, {"score": 80}]), encoding="utf-8")
    registry = _Registry(
        str(item_dir),
        {"pk": "doc-merge", "temp_txt": str(source_txt), "CombBackFN": str(combined)},
    )
    logs = []

    def fake_merge(data, **kwargs):
        logger = kwargs.get("logger")
        if logger:
            logger("[merge] scalar_conflict @score → left | L=85 | R=80")
        return data[0], {"changed": True, "counts": {"scalar_conflict": 1}, "samples": []}

    monkeypatch.setattr(merger_module, "merge_dict_slices_audited", fake_merge)
    monkeypatch.setattr(merger_module, "tlog", logs.append)
    monkeypatch.setattr(merger_module, "mark_not_running", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(merger_module, "record_adjustment", lambda *_args, **_kwargs: None)
    sink = _RetryOnceSink()
    ctx = SimpleNamespace(
        output_col="result",
        record_update_time=False,
        flatten_json_output=False,
        enable_slice_merge=True,
        merge_log_changes=True,
        cleanup_prompt_item_after_writeback=False,
        llm_source_dir=str(tmp_path),
        llm_source_backup_dir=str(tmp_path / "backup"),
    )

    merger_module.row_merger_watchdog_generic(
        ctx=ctx,
        registry=registry,
        meter_fn=lambda *_: None,
        stop_event=SimpleNamespace(is_set=lambda: True),
        sink=sink,
        scan_interval=0.001,
    )

    assert sink.calls == 2
    assert all(json.loads(row["result"]) == {"score": 85} for row in sink.write_maps)
    assert sum(line.startswith("[merge] scalar_conflict") for line in logs) == 1


def test_slice_merge_result_is_used_for_multidim_main_writeback():
    ctx = SimpleNamespace(output_profile="multidim_event", sql_writeback_rules=[])
    source = json.dumps([{"article_title": "left"}, {"article_title": "right"}])
    write_map = {"multidim_event_json": source}

    updated = merger_module._apply_slice_merge_to_write_map(
        ctx,
        write_map,
        source,
        {"article_title": "left"},
    )

    assert updated == ["multidim_event_json"]
    assert json.loads(write_map["multidim_event_json"]) == [{"article_title": "left"}]


def test_premerged_combined_dict_uses_multidim_writeback_contract(tmp_path: Path, monkeypatch):
    item_dir = tmp_path / "prompt_item"
    item_dir.mkdir()
    source_txt = tmp_path / "source.txt"
    source_txt.write_text("article", encoding="utf-8")
    premerged = {
        "article_title": "left",
        "article_date_iso": None,
        "article_date_precision": "unknown",
        "Event": [],
    }
    combined = tmp_path / "combined.txt"
    combined.write_text(json.dumps(premerged), encoding="utf-8")
    registry = _Registry(
        str(item_dir),
        {"pk": "doc-premerged", "temp_txt": str(source_txt), "CombBackFN": str(combined)},
    )
    monkeypatch.setattr(merger_module, "mark_not_running", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(merger_module, "record_adjustment", lambda *_args, **_kwargs: None)
    sink = _CaptureMultidimSink()
    ctx = SimpleNamespace(
        output_col="multidim_event_json",
        output_profile="multidim_event",
        record_update_time=False,
        flatten_json_output=False,
        enable_slice_merge=True,
        cleanup_prompt_item_after_writeback=False,
        llm_source_dir=str(tmp_path),
        llm_source_backup_dir=str(tmp_path / "backup"),
    )

    merger_module.row_merger_watchdog_generic(
        ctx=ctx,
        registry=registry,
        meter_fn=lambda *_: None,
        stop_event=SimpleNamespace(is_set=lambda: True),
        sink=sink,
        scan_interval=0.001,
    )

    assert json.loads(sink.write_maps[0]["multidim_event_json"]) == [premerged]


def test_premerged_combined_dict_remains_object_for_generic_json():
    premerged = {"article_title": "left", "Event": []}
    write_map = {"result_json": json.dumps(premerged)}
    ctx = SimpleNamespace(output_profile="json", sql_writeback_rules=[])

    updated = merger_module._apply_premerged_combined_slice_merge(
        ctx, write_map, {"result_json": "combined"}
    )

    decoded = json.loads(write_map["result_json"])
    assert updated == ["result_json"]
    assert decoded == premerged
    assert not isinstance(decoded, list)


def test_premerged_stage_dict_is_not_repaired_as_combined_output():
    invalid_stage_payload = {"article_title": "stage emitted the wrong outer shape"}
    write_map = {"multidim_event_json": json.dumps(invalid_stage_payload)}
    ctx = SimpleNamespace(output_profile="multidim_event", sql_writeback_rules=[])

    updated = merger_module._apply_premerged_combined_slice_merge(
        ctx, write_map, {"multidim_event_json": "stage:extract"}
    )

    assert updated == []
    assert json.loads(write_map["multidim_event_json"]) == invalid_stage_payload
    with pytest.raises(
        TypeError,
        match=r"multidim_event_json must be a JSON array; got dict",
    ):
        normalize_multidim_event_payload(json.loads(write_map["multidim_event_json"]))


def test_slice_merge_does_not_overwrite_unrelated_writeback_rule():
    ctx = SimpleNamespace(output_profile="json", sql_writeback_rules=[])
    source = json.dumps([{"score": 85}, {"score": 80}])
    write_map = {"merged_result": source, "route": json.dumps({"route": "news"})}

    merger_module._apply_slice_merge_to_write_map(ctx, write_map, source, {"score": 85})

    assert json.loads(write_map["merged_result"]) == {"score": 85}
    assert json.loads(write_map["route"]) == {"route": "news"}
