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


def test_invalid_local_event_link_is_terminal_without_recombining(tmp_path: Path, monkeypatch):
    """An unchanged completed input cannot spin on the same bad Event FK."""
    from czjLLM.utilities.slice_merge import MultidimEventReferenceError

    item_dir = tmp_path / "item"
    success = item_dir / "Success"
    success.mkdir(parents=True)
    (success / "0.txt").write_text("cached fragment 0", encoding="utf-8")
    (success / "1.txt").write_text("cached fragment 1", encoding="utf-8")
    source_txt = tmp_path / "raw" / "document.txt"
    source_txt.parent.mkdir()
    source_txt.write_text("original document", encoding="utf-8")
    dest = tmp_path / "finished" / "merged.txt"
    dest.parent.mkdir()
    registry = _Registry(
        str(item_dir),
        {"pk": "invalid-local-fk", "temp_txt": str(source_txt),
         "CombBackFN": str(dest), "chunks": 2},
    )
    combine_calls, releases, audits, sink_calls = [], [], [], []

    def always_fails(_item_dir, _ctx):
        combine_calls.append(_item_dir)
        raise MultidimEventReferenceError(
            "multidim slice 2 Involved_Parties references "
            "missing local Event.event_id 'E3'"
        )

    class Sink:
        def open(self):
            pass

        def close(self):
            pass

        def write_main(self, *_args, **_kwargs):
            sink_calls.append(True)

    monkeypatch.setattr(merger_module, "combine_api_finished_item", always_fails)
    monkeypatch.setattr(
        merger_module, "mark_not_running",
        lambda _ctx, pk, state: releases.append((pk, state)),
    )
    monkeypatch.setattr(
        merger_module, "record_adjustment",
        lambda _ctx, event, pk=None, **extra:
            audits.append((event, pk, extra)) or (tmp_path / "adjustments.jsonl"),
    )
    ctx = SimpleNamespace(
        output_col="multidim_event_json", output_profile="multidim_event",
        merge_slices=True, record_update_time=False,
        flatten_json_output=False,
        llm_source_dir=str(tmp_path / "raw"),
        llm_source_backup_dir=str(tmp_path / "backup"),
    )
    # Race the fallback claimant against Row Merger's registry.remove().
    # The Row Merger must still own a 'terminal' claim at this boundary.
    from czjLLM.reduction.production_control import (
        finish_legacy_merge_item, try_begin_legacy_merge_item,
    )
    claim_attempts = []
    old_remove = registry.remove

    def racing_remove(path):
        claim_attempts.append(try_begin_legacy_merge_item(ctx, path))
        old_remove(path)

    registry.remove = racing_remove
    done_q = queue.Queue()
    merger_module.row_merger_watchdog_generic(
        ctx, registry, lambda *_: None,
        SimpleNamespace(is_set=lambda: True),
        Sink(), scan_interval=0.001, done_q=done_q,
    )
    assert claim_attempts == [False], "fallback must not reclaim before removal"
    # Even a late error cleanup must not reopen a terminal failure in this run.
    finish_legacy_merge_item(ctx, str(item_dir), success=False)
    assert not try_begin_legacy_merge_item(ctx, str(item_dir))
    assert try_begin_legacy_merge_item(SimpleNamespace(), str(item_dir))
    assert len(combine_calls) == 1, "avoid watchdog retry storms"
    assert not sink_calls
    assert registry.removed
    assert releases == [("invalid-local-fk", "writeback_failed_schema")]
    assert [(event, pk) for event, pk, _ in audits] == [
        ("writeback_failed_schema_release", "invalid-local-fk")
    ]
    assert audits[0][2]["combined_result_path"] == str(dest)
    assert done_q.get_nowait() == 1
    assert source_txt.read_text(encoding="utf-8") == "original document"
    assert len(list(success.glob("*.txt"))) == 2
    assert not dest.exists()


def test_row_merger_direct_json_merge_retains_terminal_claim_until_removal(
    tmp_path: Path, monkeypatch,
):
    """The direct JSON merge error must not race post-drain fallback either."""
    from czjLLM.reduction.production_control import (
        try_begin_legacy_merge_item,
    )

    item_dir = tmp_path / "item"
    item_dir.mkdir()
    source = tmp_path / "source.txt"
    source.write_text("source text", encoding="utf-8")
    combined = tmp_path / "merged.json"
    combined.write_text(json.dumps([{
        "Event": [{"event_id": "E1"}],
        "Person": [{"event_ids": ["E3"], "name": "wrong reference"}],
    }]), encoding="utf-8")
    registry = _Registry(
        str(item_dir),
        {"pk": "direct-invalid-fk", "temp_txt": str(source),
         "CombBackFN": str(combined)},
    )
    claims_at_removal, sink_writes = [], []
    original_remove = registry.remove

    def removal_with_fallback_probe(path):
        claims_at_removal.append(try_begin_legacy_merge_item(ctx, path))
        original_remove(path)

    registry.remove = removal_with_fallback_probe
    monkeypatch.setattr(merger_module, "mark_not_running", lambda *_a, **_k: None)
    monkeypatch.setattr(merger_module, "record_adjustment", lambda *_a, **_k: None)

    class Sink:
        def open(self):
            pass

        def close(self):
            pass

        def write_main(self, *_a, **_k):
            sink_writes.append(True)

    ctx = SimpleNamespace(
        output_col="multidim_event_json",
        output_profile="multidim_event",
        merge_slices=True,
        record_update_time=False,
        flatten_json_output=False,
        merge_log_changes=False,
        cleanup_prompt_item_after_writeback=False,
        llm_source_dir=str(tmp_path),
        llm_source_backup_dir=str(tmp_path / "backup"),
    )
    done_q = queue.Queue()
    merger_module.row_merger_watchdog_generic(
        ctx, registry, lambda *_: None,
        SimpleNamespace(is_set=lambda: True),
        Sink(), scan_interval=0.001, done_q=done_q,
    )
    assert registry.removed
    assert claims_at_removal == [False]
    assert sink_writes == []
    assert done_q.get_nowait() == 1 and done_q.empty()
    assert source.exists() and combined.exists()
    assert not try_begin_legacy_merge_item(ctx, str(item_dir))


def test_postdrain_fallback_releases_bad_local_event_link_once(tmp_path: Path, monkeypatch):
    import czjLLM.sql_mode.runtime.orchestrator as orchestrator
    from czjLLM.utilities.slice_merge import MultidimEventReferenceError

    root = tmp_path / "unwriteable-row"
    success = root / "Success"
    success.mkdir(parents=True)
    (success / "0.txt").write_text("cached model answer", encoding="utf-8")
    source = tmp_path / "raw" / "input.txt"
    source.parent.mkdir()
    source.write_text("untouched", encoding="utf-8")
    missing_combined = tmp_path / "finished" / "combined.txt"
    meta = {
        "pk": "fallback-missing-E3", "temp_txt": str(source),
        "CombBackFN": str(missing_combined),
    }
    registry = _Registry(str(root), meta)
    released, audits, meter_events, warnings = [], [], [], []
    monkeypatch.setattr(
        orchestrator, "mark_not_running",
        lambda _ctx, pk, state: released.append((pk, state)),
    )
    monkeypatch.setattr(
        orchestrator, "record_adjustment",
        lambda _ctx, event, pk=None, **kw:
            audits.append((event, pk, kw)) or (tmp_path / "audit.jsonl"),
    )
    monkeypatch.setattr(
        orchestrator, "meter_update",
        lambda path, callback: (
            meter_events.append(path),
            callback({"rows": {}, "progress": {}}),
        ),
    )
    monkeypatch.setattr(orchestrator, "tlog_warn", warnings.append)

    done_q = queue.Queue()
    ctx = SimpleNamespace(
        output_col="multidim_event_json", output_profile="multidim_event",
    )
    exc = MultidimEventReferenceError(
        "multidim slice 2 Involved_Parties references missing local Event.event_id 'E3'"
    )
    assert orchestrator._release_terminal_fallback_merge_error(
        ctx, registry, str(root), exc,
        meter_fn="meter.json", done_q=done_q,
    )
    assert registry.removed
    assert released == [("fallback-missing-E3", "writeback_failed_schema")]
    assert audits[0][:2] == (
        "writeback_failed_schema_release", "fallback-missing-E3",
    )
    assert audits[0][2]["combined_result_path"] == str(missing_combined)
    assert done_q.get_nowait() == 1
    assert len(meter_events) == 2
    assert len(warnings) == 1 and "pending" in warnings[0]
    assert source.read_text(encoding="utf-8") == "untouched"
    assert (success / "0.txt").exists()
    assert not missing_combined.exists()

    # The other owner may have removed this registry row already. Never
    # emit a duplicate completion/audit or touch the preserved source.
    assert not orchestrator._release_terminal_fallback_merge_error(
        ctx, registry, str(root), exc,
        meter_fn="meter.json", done_q=done_q,
    )
    assert len(released) == len(audits) == 1
    assert done_q.empty()


def test_terminal_fallback_claim_stays_blocked_during_registry_removal(tmp_path: Path, monkeypatch):
    """The Row Merger must not claim the same invalid slices during cleanup."""
    from czjLLM.reduction.production_control import (
        finish_legacy_merge_item,
        mark_legacy_merge_item_terminal,
        try_begin_legacy_merge_item,
    )
    import czjLLM.sql_mode.runtime.orchestrator as orchestrator
    from czjLLM.utilities.slice_merge import MultidimEventReferenceError

    item = str(tmp_path / "item")
    source = tmp_path / "input.txt"
    source.write_text("keep me", encoding="utf-8")

    class RacingRegistry:
        removed = False
        overlap_claims = []

        def get(self, path):
            return {"pk": "racing-invalid-event", "temp_txt": str(source)} if not self.removed else None

        def list_items(self):
            return {} if self.removed else {
                item: {"pk": "racing-invalid-event", "temp_txt": str(source)}
            }

        def remove(self, path):
            assert path == item
            # Simulate a concurrently polling Row Merger at the exact
            # boundary before the fallback registry item disappears.
            self.overlap_claims.append(try_begin_legacy_merge_item(ctx, item))
            self.removed = True

    registry = RacingRegistry()
    ctx = SimpleNamespace(output_col="multidim_event_json", output_profile="multidim_event")
    assert try_begin_legacy_merge_item(ctx, item)
    error = MultidimEventReferenceError(
        "multidim slice 1 evidence_snippets references missing local Event.event_id 'T1'"
    )
    monkeypatch.setattr(orchestrator, "mark_not_running", lambda *_a, **_k: None)
    monkeypatch.setattr(orchestrator, "record_adjustment", lambda *_a, **_k: None)
    monkeypatch.setattr(orchestrator, "tlog_warn", lambda *_a, **_k: None)

    mark_legacy_merge_item_terminal(ctx, item)
    assert orchestrator._release_terminal_fallback_merge_error(
        ctx, registry, item, error,
    )
    assert registry.overlap_claims == [False]
    # Another owner cannot release the terminal claim with success=False.
    finish_legacy_merge_item(ctx, item, success=False)
    assert not try_begin_legacy_merge_item(ctx, item)
    assert source.read_text(encoding="utf-8") == "keep me"

    # ES remains pending for later reanalysis; a NEW run has a fresh claim.
    assert try_begin_legacy_merge_item(SimpleNamespace(), item)


def test_chunk_local_reference_error_class_is_terminal_but_es_transport_is_not():
    from czjLLM.utilities.slice_merge import MultidimEventReferenceError
    invalid = MultidimEventReferenceError(
        "multidim slice 3 evidence_snippets references "
        "missing local Event.event_id 'T1'"
    )
    assert merger_module._is_terminal_schema_writeback_error(invalid)
    assert not merger_module._is_terminal_schema_writeback_error(
        RuntimeError("temporary ES connection refused")
    )


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
