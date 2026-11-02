"""Real-file, per-slice Worker dispatch metadata and GUI join regressions."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from threading import Event, Thread

import pytest

from czjLLM.job_manager import document_progress
from czjLLM.job_manager import worker_dispatch_observation as dispatch
from czjLLM.prompt_pipeline import pipeline_controller as pc


def _setup(tmp_path):
    item = tmp_path / "item"
    prompt = item / "RUNNING" / "chunk_001.txt"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("a test-only prompt", encoding="utf-8")
    audit = tmp_path / "llm_call_audit_20261102-1.csv"
    audit.write_text(
        "prompt_file,model,base_url,ok,error\n", encoding="utf-8",
    )
    meter = tmp_path / "loadmeter_20261102.json"
    meter.write_text(json.dumps({
        "rows": {"row": {
            "item_dir": str(item), "temp_txt": str(tmp_path / "row.txt"),
            "total": 1, "done": 0, "status": "in_progress",
            "queue_running": 1,
        }}
    }), encoding="utf-8")
    return item, prompt, audit, meter


def _emit(item, prompt, audit, call_id, status, endpoint="http://10.20.30.40:11434/v1?key=PRIVATE"):
    dispatch.write_worker_dispatch_observation(
        audit_path=str(audit), item_dir=str(item), prompt_file=str(prompt),
        worker_call_id=call_id, model_spec={
            "model_name": "qwen3.6:128k",
            "base_url": endpoint, "api_key": "PRIVATE_API_KEY",
        }, status=status,
    )


def test_real_pre_call_status_visible_at_zero_completed_slices(tmp_path):
    item, prompt, audit, meter = _setup(tmp_path)
    identity = uuid4().hex
    _emit(item, prompt, audit, identity, "assigned")
    view = document_progress.read_document_progress(meter, audit_path=str(audit))
    assert "qwen3.6:128k · 10.20.30.40:11434" in view["shown"][0]["model_endpoint"]
    assert "已分派" in view["shown"][0]["model_endpoint"]
    assert view["shown"][0]["progress"].endswith("0% (0/1)")
    _emit(item, prompt, audit, identity, "calling")
    view = document_progress.read_document_progress(meter, audit_path=str(audit))
    assert "呼叫中（最後觀測）" in view["shown"][0]["model_endpoint"]
    _emit(item, prompt, audit, identity, "returned")
    view = document_progress.read_document_progress(meter, audit_path=str(audit))
    assert "已回傳" in view["shown"][0]["model_endpoint"]
    assert "完成" not in view["shown"][0]["stage"]


def test_sanitized_metadata_no_raw_paths_credentials_urls_or_error(tmp_path):
    item, prompt, audit, _meter = _setup(tmp_path)
    _emit(item, prompt, audit, uuid4().hex, "failed",
          endpoint="http://name:password@10.1.1.1:11434/v1?token=SECRET")
    data = (audit.with_suffix(".dispatch"))
    content = next(data.rglob("*.json")).read_text(encoding="utf-8")
    for forbidden in (str(item), str(prompt), "password", "SECRET", "PRIVATE_API_KEY", "http://", "a test-only prompt"):
        assert forbidden not in content
    parsed = json.loads(content)
    assert parsed["endpoint_ip"] == ""
    assert parsed["slice_hash"] and parsed["item_hash"]
    assert parsed["status"] == "failed"
    assert dispatch.read_visible_dispatch_observations(str(audit), {"row": str(item)})["row"]["text"].endswith("IP 未記錄｜失敗（最後觀測）")


def test_two_parallel_slices_keep_distinct_call_snapshots_and_active_precedence(tmp_path):
    item, prompt, audit, _ = _setup(tmp_path)
    a, b = uuid4().hex, uuid4().hex
    second = prompt.with_name("chunk_002.txt")
    second.write_text("another test-only prompt", encoding="utf-8")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(_emit, item, prompt, audit, a, "calling", "http://10.1.1.11:11434"),
            pool.submit(_emit, item, second, audit, b, "calling", "http://10.1.1.22:11434"),
        ]
        for x in futures:
            x.result()
    found = dispatch.read_visible_dispatch_observations(str(audit), {"row": str(item)})
    assert found["row"]["count"] == 2
    assert "2 呼叫" in found["row"]["text"]
    _emit(item, prompt, audit, a, "returned", "http://10.1.1.11:11434")
    active = dispatch.read_visible_dispatch_observations(str(audit), {"row": str(item)})
    assert "10.1.1.22:11434" in active["row"]["text"]
    assert "呼叫中" in active["row"]["text"]
    _emit(item, second, audit, b, "failed", "http://10.1.1.22:11434")
    finished = dispatch.read_visible_dispatch_observations(str(audit), {"row": str(item)})
    assert "失敗（最後觀測）" in finished["row"]["text"]


def test_item_prefix_collision_does_not_leak_other_row(tmp_path):
    item, prompt, audit, meter = _setup(tmp_path)
    other = tmp_path / "item_more"
    other_prompt = other / "RUNNING" / "same_name.txt"
    other_prompt.parent.mkdir(parents=True)
    other_prompt.write_text("test", encoding="utf-8")
    _emit(other, other_prompt, audit, uuid4().hex, "calling",
          endpoint="http://10.9.9.9:11434")
    evidence = dispatch.read_visible_dispatch_observations(
        str(audit), {"row": str(item), "other": str(other)},
    )
    assert evidence["row"]["text"] == ""
    assert "10.9.9.9:11434" in evidence["other"]["text"]


def test_unsafe_symlink_and_oversized_entry_fail_closed(tmp_path):
    item, prompt, audit, _ = _setup(tmp_path)
    _emit(item, prompt, audit, uuid4().hex, "calling")
    root = audit.with_suffix(".dispatch")
    target = next(root.rglob("*.json"))
    target.write_bytes(b"X" * (dispatch.MAX_RECORD_BYTES + 1))
    with pytest.raises(ValueError, match="unsafe"):
        dispatch.read_visible_dispatch_observations(str(audit), {"r": str(item)})
    target.unlink()
    external = tmp_path / "elsewhere.json"
    external.write_text("{}", encoding="utf-8")
    try:
        target.symlink_to(external)
    except (OSError, NotImplementedError):
        pass
    else:
        with pytest.raises(ValueError):
            dispatch.read_visible_dispatch_observations(str(audit), {"r": str(item)})


def test_actual_worker_call_emits_before_blocked_api_returns(tmp_path, monkeypatch):
    item, prompt, audit, meter = _setup(tmp_path)
    entered, release = Event(), Event()
    monkeypatch.setattr(pc, "select_idle_ollama_url", lambda *args, **kw: "http://10.99.0.3:11434")
    monkeypatch.setattr(pc, "release_url_load", lambda *args, **kw: None)
    monkeypatch.setattr(pc, "verified_queued_prompt_source", lambda *args, **kw: False)
    monkeypatch.setattr(pc, "log_llm_call", lambda **kw: None)
    def call_api(*args, **kwargs):
        entered.set()
        assert release.wait(10), "test must release the simulated LLM call"
        return SimpleNamespace(
            usage=SimpleNamespace(completion_tokens=4),
            choices=[SimpleNamespace(message=SimpleNamespace(content="OK"))],
        ), 0.0
    monkeypatch.setattr(pc, "CallLLMAPI", call_api)
    job = pc.PromptAPIPipeline(
        promptFile=str(prompt), OutputSaveFN="", removeFinPromptFile=False,
        task="summarize", max_tokens=128, allow_to_retry=False,
        model_spec={"model_name": "qwen3.6:128k", "base_url": ["http://10.99.0.3:11434"]},
        audit_run_id="20261102-1", audit_path=str(audit),
        dispatch_item_dir=str(item),
    )
    out = []
    def run():
        out.append(job.proc())
    worker = Thread(target=run, daemon=True)
    worker.start()
    try:
        assert entered.wait(10), "Worker never reached CallLLMAPI"
        view = document_progress.read_document_progress(meter, audit_path=str(audit))
        assert "10.99.0.3:11434" in view["shown"][0]["model_endpoint"]
        assert "呼叫中" in view["shown"][0]["model_endpoint"]
        assert view["shown"][0]["progress"].endswith("0% (0/1)")
    finally:
        release.set()
        worker.join(timeout=10)
    assert not worker.is_alive()
    assert out and out[0]["ok"]
    view = document_progress.read_document_progress(meter, audit_path=str(audit))
    assert "已回傳" in view["shown"][0]["model_endpoint"]


def test_no_job_item_dir_means_no_guessed_row_event(tmp_path):
    item, prompt, audit, _ = _setup(tmp_path)
    # Legacy/direct jobs without explicit row association fail closed.
    with pytest.raises(ValueError):
        dispatch.write_worker_dispatch_observation(
            audit_path=str(audit), item_dir="", prompt_file=str(prompt),
            worker_call_id=uuid4().hex,
            model_spec={"model_name": "qwen3.6", "base_url": "http://10.1.1.1"},
            status="calling",
        )
    assert not audit.with_suffix(".dispatch").exists()


def test_dispatch_import_is_module_scoped_not_suppressed_by_observer_try():
    import inspect
    source = inspect.getsource(pc)
    assert ("from czjLLM.job_manager.worker_dispatch_observation import "
            "write_worker_dispatch_observation") in source
    method = inspect.getsource(pc.PromptAPIPipeline._record_dispatch_observation)
    assert "import write_worker_dispatch_observation" not in method
    assert "write_worker_dispatch_observation(" in method


def test_legacy_worker_without_optional_dispatch_item_dir_is_noop(tmp_path):
    # Existing isolated Worker/repair tests use __new__ without running the
    # constructor. Observability must never interrupt those production paths.
    worker = pc.PromptAPIPipeline.__new__(pc.PromptAPIPipeline)
    worker.audit_path = str(tmp_path / "llm_call_audit_legacy.csv")
    worker.promptFile = str(tmp_path / "input.txt")
    worker._record_dispatch_observation(uuid4().hex, "assigned")
    assert not (tmp_path / "llm_call_audit_legacy.dispatch").exists()
