from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from czjLLM.sql_mode.runtime.row_merger_generic import row_merger_watchdog_generic
from czjLLM.reduction.production_control import (
    ensure_production_observer, request_execution_cancel,
)


class _RegistryStub:
    def __init__(self, item_dir: str, meta: dict) -> None:
        self.item_dir = item_dir
        self.meta = meta
        self.removed = False

    def list_items(self):
        return {} if self.removed else {self.item_dir: self.meta}

    def remove(self, _item_dir: str):
        self.removed = True


class _StopEventStub:
    def __init__(self, is_set: bool = True) -> None:
        self._is_set = is_set

    def is_set(self):
        return self._is_set


class _SinkStub:
    def __init__(self) -> None:
        self.writes = []

    def open(self):
        return None

    def write_main(self, pk, result_text, update_time=None):
        self.writes.append((pk, result_text, update_time))

    def close(self):
        return None


def test_row_merger_writes_when_combined_exists_even_if_todo_remaining(tmp_path: Path):
    item_dir = tmp_path / "prompt_item"
    todo_dir = item_dir / "TODO"
    todo_dir.mkdir(parents=True, exist_ok=True)
    (todo_dir / "0.txt").write_text("still here", encoding="utf-8")

    source_txt = tmp_path / "src" / "cache" / "excel_input_1.txt"
    source_txt.parent.mkdir(parents=True, exist_ok=True)
    source_txt.write_text("raw input", encoding="utf-8")

    combined = tmp_path / "finished" / "cache" / "excel_input_1_result.txt"
    combined.parent.mkdir(parents=True, exist_ok=True)
    combined.write_text(json.dumps({"ok": True}, ensure_ascii=False), encoding="utf-8")

    registry = _RegistryStub(
        item_dir=str(item_dir),
        meta={"pk": 1, "temp_txt": str(source_txt), "CombBackFN": str(combined)},
    )
    sink = _SinkStub()
    stop_event = _StopEventStub(is_set=True)
    ctx = SimpleNamespace(
        output_col="File_result",
        record_update_time=False,
        flatten_json_output=False,
        cleanup_prompt_item_after_writeback=False,
        llm_source_dir=str(tmp_path / "src"),
        llm_source_backup_dir=str(tmp_path / "backup"),
    )

    row_merger_watchdog_generic(
        ctx=ctx,
        registry=registry,
        meter_fn=lambda *_: None,
        stop_event=stop_event,
        sink=sink,
        scan_interval=0.01,
        done_q=None,
    )

    assert registry.removed is True
    assert len(sink.writes) == 1
    pk, write_map, _ = sink.writes[0]
    assert pk == 1
    assert write_map["File_result"] == json.dumps({"ok": True}, ensure_ascii=False)


def test_cancelled_run_still_drains_existing_deterministic_combined_output(tmp_path: Path):
    item_dir = tmp_path / "item"; item_dir.mkdir()
    source = tmp_path / "src/cache/input.txt"; source.parent.mkdir(parents=True); source.write_text("raw")
    combined = tmp_path / "out/result.txt"; combined.parent.mkdir(parents=True); combined.write_text("done")
    registry = _RegistryStub(str(item_dir), {"pk": 7, "temp_txt": str(source), "CombBackFN": str(combined)})
    sink = _SinkStub()
    ctx = SimpleNamespace(output_col="File_result", record_update_time=False,
                          flatten_json_output=False, cleanup_prompt_item_after_writeback=False,
                          llm_source_dir=str(tmp_path / "src"), llm_source_backup_dir=str(tmp_path / "backup"),
                          PGMSubDir=str(tmp_path), mode="sql")
    request_execution_cancel(ctx, source="external")
    row_merger_watchdog_generic(ctx, registry, lambda *_: None, _StopEventStub(True), sink,
                                scan_interval=.01, done_q=None)
    assert registry.removed and sink.writes[0][1]["File_result"] == "done"


def test_cancelled_semantic_combine_is_released_without_write_or_spin(tmp_path: Path, monkeypatch):
    import czjLLM.sql_mode.runtime.row_merger_generic as module
    from czjLLM.reduction.execution import ExecutionCancelled
    item_dir = tmp_path / "item"; (item_dir / "Success").mkdir(parents=True)
    (item_dir / "Success/0.txt").write_text("finished leaf")
    source = tmp_path / "src/cache/input.txt"; source.parent.mkdir(parents=True); source.write_text("raw")
    registry = _RegistryStub(str(item_dir), {"pk": 8, "temp_txt": str(source), "CombBackFN": ""})
    sink = _SinkStub(); states = []
    monkeypatch.setattr(module, "combine_api_finished_item",
                        lambda *a, **k: (_ for _ in ()).throw(ExecutionCancelled("cancelled")))
    monkeypatch.setattr(module, "get_combined_result_path", lambda *a: str(tmp_path / "out/result.txt"))
    monkeypatch.setattr(module, "mark_not_running", lambda _ctx, _pk, state: states.append(state))
    monkeypatch.setattr(module, "record_adjustment", lambda *a, **k: None)
    ctx = SimpleNamespace(output_col="File_result", record_update_time=False,
                          flatten_json_output=False, cleanup_prompt_item_after_writeback=False,
                          llm_source_dir=str(tmp_path / "src"), llm_source_backup_dir=str(tmp_path / "backup"))
    row_merger_watchdog_generic(ctx, registry, lambda *_: None, _StopEventStub(True), sink,
                                scan_interval=.01, done_q=None)
    assert registry.removed and states == ["cancelled"] and sink.writes == []
    assert (item_dir / "Success/0.txt").read_text() == "finished leaf"



def test_row_merger_emits_legacy_merge_telemetry_on_actual_combine_path(
    tmp_path: Path, monkeypatch
):
    import czjLLM.sql_mode.runtime.row_merger_generic as module

    item_dir = tmp_path / "item"
    success = item_dir / "Success"
    success.mkdir(parents=True)
    (success / "0.txt").write_text(
        json.dumps([{"value": 1}, {"value": 2}], ensure_ascii=False),
        encoding="utf-8",
    )
    source = tmp_path / "src/cache/input.txt"
    source.parent.mkdir(parents=True)
    source.write_text("raw", encoding="utf-8")
    combined = tmp_path / "out/result.txt"

    def _combine(_item_dir, _ctx):
        combined.parent.mkdir(parents=True, exist_ok=True)
        combined.write_text(
            json.dumps({"value": 2}, ensure_ascii=False),
            encoding="utf-8",
        )
        return str(combined)

    monkeypatch.setattr(module, "combine_api_finished_item", _combine)
    monkeypatch.setattr(module, "get_combined_result_path", lambda *_a: str(combined))

    registry = _RegistryStub(
        str(item_dir),
        {"pk": 9, "temp_txt": str(source), "CombBackFN": "", "chunks": 1},
    )
    sink = _SinkStub()
    ctx = SimpleNamespace(
        output_col="File_result",
        record_update_time=False,
        flatten_json_output=False,
        cleanup_prompt_item_after_writeback=False,
        llm_source_dir=str(tmp_path / "src"),
        llm_source_backup_dir=str(tmp_path / "backup"),
        PGMSubDir=str(tmp_path),
        mode="es",
        merge_slices=True,
    )

    row_merger_watchdog_generic(
        ctx, registry, lambda *_: None, _StopEventStub(True), sink,
        scan_interval=.01, done_q=None,
    )

    stats = ensure_production_observer(ctx).snapshot()
    assert stats["activity_mode"] == "legacy_merge_slices"
    assert stats["legacy_merges_started"] == 1
    assert stats["legacy_merges_completed"] == 1
    assert stats["legacy_merges_failed"] == 0
    assert registry.removed and len(sink.writes) == 1
