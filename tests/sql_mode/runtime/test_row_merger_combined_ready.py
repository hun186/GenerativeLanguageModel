from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from czjLLM.sql_mode.runtime.row_merger_generic import row_merger_watchdog_generic


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
