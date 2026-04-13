from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from czjLLM.sql_mode.runtime import scheduler


class _RegistryStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str, str]] = []

    def add(self, item_dir, pk, temp_txt_path, comb_back_fn):
        self.calls.append((item_dir, pk, temp_txt_path, comb_back_fn))


def test_schedule_one_row_prefers_real_multistage_merged_path(tmp_path, monkeypatch):
    temp_txt = tmp_path / "src" / "cache" / "excel_input_1.txt"
    temp_txt.parent.mkdir(parents=True, exist_ok=True)
    temp_txt.write_text("input", encoding="utf-8")

    item_dir = tmp_path / "prompt" / "excel_input_1"
    todo_dir = item_dir / "TODO"
    todo_dir.mkdir(parents=True, exist_ok=True)
    (todo_dir / "0.txt").write_text("todo", encoding="utf-8")

    merged_out = tmp_path / "finished" / "cache" / "excel_input_1_route_extract_hash.txt"
    merged_out.parent.mkdir(parents=True, exist_ok=True)
    merged_out.write_text("merged", encoding="utf-8")

    fallback_out = tmp_path / "finished" / "cache" / "excel_input_1_legacy-task.txt"

    monkeypatch.setattr(scheduler, "save_text_as_temp_file", lambda **_: str(temp_txt))
    monkeypatch.setattr(scheduler, "handle_single_input_file", lambda *_, **__: None)
    monkeypatch.setattr(scheduler, "find_item_dir_for", lambda *_: str(item_dir))
    monkeypatch.setattr(scheduler, "_run_with_timeout", lambda fn, timeout_sec: (True, fn()))
    monkeypatch.setattr(scheduler, "process_prompt_and_merge", lambda *_args, **_kwargs: str(merged_out))
    monkeypatch.setattr(scheduler, "get_combined_result_path", lambda *_: str(fallback_out))
    monkeypatch.setattr(scheduler, "meter_update", lambda *_: None)

    ctx = SimpleNamespace(
        llm_source_dir=str(tmp_path / "src"),
        llm_source_finished_dir=str(tmp_path / "finished"),
        prompt_dir=str(tmp_path / "prompt"),
        mode="sql",
        sql_enable_multistage_stream=True,
        stages=[{"name": "route", "task": "分類"}, {"name": "extract", "task_key": "T"}],
        mock_llm_mode=False,
        _faulthandler_fp=None,
        slice_timeout_sec=10.0,
    )
    registry = _RegistryStub()

    chunks = scheduler.schedule_one_row(ctx, registry, meter_fn=lambda *_: None, idx=0, pk=1, text="x")

    assert chunks == 1
    assert len(registry.calls) == 1
    _, _, _, comb_back_fn = registry.calls[0]
    assert comb_back_fn == str(merged_out)
