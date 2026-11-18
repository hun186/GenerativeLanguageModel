"""Offline RAM-only JSON repair sample and GUI IPC tests (no ES/LLM)."""
from __future__ import annotations

import json
import queue
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from czjLLM.utilities.json_repair_memory import (
    MAX_CASES, RepairMemoryRing, clear_gui_repair_sink,
    drain_private_repair_queue, gui_capture_active, publish_gui_repair,
    set_gui_repair_sink,
)


def test_recent_50_fifo_eviction_and_exact_run_event_readback():
    ring = RepairMemoryRing()
    pairs = []
    for n in range(MAX_CASES + 1):
        run = "run-A" if n % 2 else "run-B"
        event = uuid4().hex
        assert ring.add(run, event, f"PRIVATE_before_{n}", f"PRIVATE_after_{n}")
        pairs.append((run, event))
    assert ring.count == 50
    assert ring.total_bytes > 0
    with pytest.raises(ValueError, match="MEMORY_REPAIR_NOT_AVAILABLE"):
        ring.read(*pairs[0])
    assert ring.read(*pairs[-1])["repaired"] == "PRIVATE_after_50"
    with pytest.raises(ValueError, match="MEMORY_REPAIR_NOT_AVAILABLE"):
        ring.read("wrong-run", pairs[-1][1])


def test_global_encoded_byte_budget_evicts_oldest(monkeypatch):
    import czjLLM.utilities.json_repair_memory as mod
    monkeypatch.setattr(mod, "MAX_TOTAL_BYTES", 1100)
    ring = RepairMemoryRing()
    ids = [uuid4().hex for _ in range(3)]
    for event in ids:
        assert ring.add("run", event, "X" * 200, "Y" * 200)
    assert ring.count == 2
    assert ring.total_bytes <= 1100
    with pytest.raises(ValueError, match="MEMORY_REPAIR_NOT_AVAILABLE"):
        ring.read("run", ids[0])
    assert ring.read("run", ids[2])["original"] == "X" * 200


def test_oversize_surrogate_bad_uuid_and_duplicate_cannot_pollute_ring():
    ring = RepairMemoryRing()
    eid = uuid4().hex
    assert ring.add("one", eid, "original", "repaired")
    assert not ring.add("one", eid, "attacker", "overwritten")
    assert ring.read("one", eid)["original"] == "original"
    assert ring.add("two", eid, "other run", "different")
    assert not ring.add("one", uuid4().hex, "X" * 80001, "after")
    assert not ring.add("one", uuid4().hex, "\ud800", "after")
    assert not ring.add("one", "not-uuid", "a", "b")
    assert ring.count == 2
    assert ring.clear_run("one") == 1
    assert ring.read("two", eid)["original"] == "other run"
    ring.clear()
    assert ring.count == 0 and ring.total_bytes == 0


def test_private_ipc_is_bounded_separate_and_only_readable_by_gui_ring():
    from czjLLM.job_manager.win_gui import _GUIClient
    controls = queue.Queue()
    private = queue.Queue(maxsize=2)
    client = _GUIClient(controls, SimpleNamespace(is_alive=lambda: True),
                        private_repair_q=private)
    e1, e2, e3 = uuid4().hex, uuid4().hex, uuid4().hex
    try:
        set_gui_repair_sink(client.offer_repair)
        assert gui_capture_active()
        assert publish_gui_repair("run", e1, "PRIVATE 1", "RESULT 1")
        assert publish_gui_repair("run", e2, "PRIVATE 2", "RESULT 2")
        assert not publish_gui_repair("run", e3, "PRIVATE 3", "RESULT 3")
        assert controls.empty(), "raw strings must never go into GUI log/control queue"
        ring = RepairMemoryRing()
        assert drain_private_repair_queue(private, ring) == 2
        assert ring.count == 2
        assert ring.read("run", e1)["original"] == "PRIVATE 1"
    finally:
        clear_gui_repair_sink(client.offer_repair)
    assert not gui_capture_active()
    assert not publish_gui_repair("run", uuid4().hex, "SECRET", "FIX")


def test_gui_close_unregisters_bound_sink():
    from czjLLM.job_manager.win_gui import _GUIClient, _GuiEvents
    controls = queue.Queue()
    process = SimpleNamespace(is_alive=lambda: False)
    client = _GUIClient(controls, process, private_repair_q=queue.Queue(maxsize=2))
    set_gui_repair_sink(client.offer_repair)
    client.close()
    assert not gui_capture_active()
    assert controls.get_nowait() == (_GuiEvents.CLOSE, None)


def test_worker_memory_only_success_is_exact_quality_linked_and_not_written(
    tmp_path, monkeypatch, capsys,
):
    import czjLLM.prompt_pipeline.pipeline_controller as pc
    from czjLLM.utilities.processing_quality import quality_event_path

    monkeypatch.delenv("CZJLLM_JSON_REPAIR_CAPTURE", raising=False)
    monkeypatch.delenv("CZJLLM_JSON_REPAIR_PRIVATE_DIR", raising=False)
    pair = ('{"PRIVATE_NAME":"value" "ok":1}',
            '{"PRIVATE_NAME":"value","ok":1}')
    monkeypatch.setattr(pc, "json_format_caller", lambda **_: pair[1])
    input_file = tmp_path / "RUNNING" / "repair.txt"
    input_file.parent.mkdir()
    input_file.write_text("synthetic", encoding="utf-8")
    audit = tmp_path / "llm_call_audit_run.csv"
    ring = RepairMemoryRing()

    def receiver(run, event, before, after):
        return ring.add(run, event, before, after)

    set_gui_repair_sink(receiver)
    try:
        worker = pc.PromptAPIPipeline(
            task="to json", content="", promptFile=str(input_file),
            model_spec={"model_name": "dummy", "base_url": ["http://invalid.local"]},
            audit_run_id="gui-run", audit_path=str(audit),
        )
        monkeypatch.setattr(worker, "extract_MainFileName_and_input_text",
                            lambda: ("", "", ""))
        rest, output = worker.handle_json_output(pair[0])
        assert rest == [] and output == pair[1]
        records = [json.loads(x) for x in quality_event_path(str(audit)).read_text(
            encoding="utf-8").splitlines()]
        success = next(x for x in records if x["code"] == "JSON_REPAIR_SUCCEEDED")
        assert ring.read("gui-run", success["event_id"]) == {
            "original": pair[0], "repaired": pair[1],
        }
        assert ring.count == 1
        assert "PRIVATE_NAME" not in json.dumps(records)
        assert "PRIVATE_NAME" not in capsys.readouterr().out
        assert not (tmp_path / ".runtime-private").exists()
        assert not list(tmp_path.rglob("r-*.json"))
    finally:
        clear_gui_repair_sink(receiver)


def test_headless_without_gui_never_captures_raw(tmp_path, monkeypatch, capsys):
    import czjLLM.prompt_pipeline.pipeline_controller as pc
    import czjLLM.utilities.json_repair_private_capture as cap

    clear_gui_repair_sink()
    monkeypatch.delenv(cap.ENABLE_ENV, raising=False)
    monkeypatch.delenv(cap.ROOT_ENV, raising=False)
    assert cap.capture_enabled() is False
    assert cap.startup_private_capture_maintenance() == "DISABLED"
    assert not gui_capture_active()
    monkeypatch.setattr(pc, "json_format_caller", lambda **_: '{"a":1}')
    path = tmp_path / "RUNNING" / "one.txt"
    path.parent.mkdir()
    path.write_text("synthetic", encoding="utf-8")
    worker = pc.PromptAPIPipeline(
        task="to json", content="", promptFile=str(path),
        model_spec={"model_name": "dummy", "base_url": ["http://invalid.local"]},
        audit_run_id="linux", audit_path=str(tmp_path / "llm_call_audit_run.csv"),
    )
    monkeypatch.setattr(worker, "extract_MainFileName_and_input_text",
                        lambda: ("", "", ""))
    assert worker.handle_json_output('{"a":1,}')[1] == '{"a":1}'
    assert not list(tmp_path.rglob("r-*.json"))
    assert "PRIVATE_JSON_REPAIR_CAPTURE_UNAVAILABLE" not in capsys.readouterr().out


def test_gui_wiring_uses_separate_spawn_queue_not_quality_payload():
    source = (Path(__file__).resolve().parents[1] /
              "czjLLM/job_manager/win_gui.py").read_text(encoding="utf-8")
    popup = (Path(__file__).resolve().parents[1] /
             "czjLLM/job_manager/json_repair_review_gui.py").read_text(encoding="utf-8")
    assert "ctx.Queue(maxsize=MAX_PENDING_IPC)" in source
    assert "set_gui_repair_sink(client.offer_repair)" in source
    assert "drain_private_repair_queue(private_repair_q, _repair_memory)" in source
    assert "memory_ring=_repair_memory" in source
    assert "memory_ring.read(" in popup
    assert '[:50]' in popup
    assert "記憶體最新 50 筆" in popup
