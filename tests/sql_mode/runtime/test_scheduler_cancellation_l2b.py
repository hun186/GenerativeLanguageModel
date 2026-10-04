import importlib.util
import sys
import threading
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from czjLLM.reduction.execution import ExecutionCancelled


def _module(name, **attrs):
    value = types.ModuleType(name)
    for key, attr in attrs.items(): setattr(value, key, attr)
    sys.modules[name] = value


def _load_scheduler():
    names = [
        "utils.utilities_path", "czjLLM.prompt_pipeline.pipeline_controller",
        "czjLLM.prompt_pipeline.runtime_support.stage_mode", "czjLLM.utilities.file_utils",
        "czjLLM.job_manager.console_ui", "czjLLM.job_manager.job_config",
        "czjLLM.handlers.handle_txt_file", "czjLLM.utilities.path_utils",
    ]
    old = {name: sys.modules.get(name) for name in names}
    _module("utils.utilities_path", safe_move=lambda *a: None, MKDIR=lambda p: Path(p).mkdir(parents=True, exist_ok=True),
            getPathFromFN=lambda p: str(Path(p).parent), getMFNFromFN=lambda p: Path(p).stem,
            OSWALK=lambda p: [str(x) for x in Path(p).rglob("*") if x.is_file()])
    _module("czjLLM.prompt_pipeline.pipeline_controller", find_item_dir_for=lambda *a: "",
            meter_update=lambda *a: None, process_prompt_and_merge=lambda *a, **k: "")
    _module("czjLLM.prompt_pipeline.runtime_support.stage_mode", explicit_stage_flow=lambda ctx: ctx.stages)
    _module("czjLLM.utilities.file_utils", save_text_as_temp_file=lambda **k: "")
    _module("czjLLM.job_manager.console_ui", tlog=lambda *a: None, tlog_warn=lambda *a: None)
    class Overlay:
        def __init__(self, base, **values): self._base = base; self.__dict__.update(values)
        def __getattr__(self, name): return getattr(self._base, name)
    _module("czjLLM.job_manager.job_config", CtxOverlay=Overlay)
    _module("czjLLM.handlers.handle_txt_file", handle_single_input_file=lambda *a, **k: None)
    _module("czjLLM.utilities.path_utils", get_combined_result_path=lambda *a: "combined.txt")
    path = Path(__file__).resolve().parents[3] / "czjLLM/sql_mode/runtime/scheduler.py"
    spec = importlib.util.spec_from_file_location("czjLLM.sql_mode.runtime.scheduler_l2b", path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        for name, value in old.items():
            if value is None: sys.modules.pop(name, None)
            else: sys.modules[name] = value
    return module


def test_schedule_one_row_propagates_cancel_and_drains_registration(tmp_path, monkeypatch):
    scheduler = _load_scheduler()
    source = tmp_path / "source/cache/input.txt"; source.parent.mkdir(parents=True); source.write_text("row")
    item = tmp_path / "prompt/item"; (item / "TODO").mkdir(parents=True); (item / "TODO/0.txt").write_text("prompt")
    monkeypatch.setattr(scheduler, "save_text_as_temp_file", lambda **kw: str(source))
    monkeypatch.setattr(scheduler, "_run_with_timeout", lambda *a, **k: (True, "ok"))
    monkeypatch.setattr(scheduler, "find_item_dir_for", lambda *a: str(item))
    monkeypatch.setattr(scheduler, "process_prompt_and_merge",
                        lambda *a, **k: (_ for _ in ()).throw(ExecutionCancelled("cancelled")))
    meter = {"rows": {}, "queue": {"pending": 0}, "progress": {}}
    monkeypatch.setattr(scheduler, "meter_update", lambda _fn, update: update(meter))
    class Registry:
        def __init__(self): self.items = {}
        def add(self, path, pk, temp, combined): self.items[path] = {"pk": pk}
        def update(self, path, **fields): self.items[path].update(fields)
        def remove(self, path): self.items.pop(path, None)
    registry = Registry()
    ctx = SimpleNamespace(llm_source_dir=str(tmp_path / "source"), llm_source_finished_dir=str(tmp_path / "finished"),
                          prompt_dir=str(tmp_path / "prompt"), mode="sql", stages=[{"name": "one", "task": "safe"}],
                          sql_enable_multistage_stream=True, _faulthandler_fp=None)
    with pytest.raises(ExecutionCancelled):
        scheduler.schedule_one_row(ctx, registry, "meter", 0, "pk-1", "row")
    assert registry.items == {}
    assert meter["rows"]["pk-1"]["status"] == "cancelled"
    assert meter["queue"]["pending"] == 0
