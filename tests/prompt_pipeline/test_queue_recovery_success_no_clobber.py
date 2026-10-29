"""Real filesystem no-clobber regressions for RUNNING recovery and Success output."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from czjLLM.prompt_pipeline import pipeline_controller as pc
from czjLLM.prompt_pipeline.runtime_support import prompt_queue as queue
from czjLLM.prompt_pipeline.runtime_support.queue_observation import (
    summarize_queue_observations,
)


def _setup_running(tmp_path, data=b"running private input", *, nested=""):
    item = tmp_path / "item"
    running = item / "RUNNING"
    if nested:
        running /= nested
    running.mkdir(parents=True, exist_ok=True)
    src = running / "root.txt"
    src.write_bytes(data)
    return item, src


def test_existing_todo_is_never_replaced_by_recovery(tmp_path):
    item, running = _setup_running(tmp_path, b"running generation")
    todo = item / "TODO"
    todo.mkdir()
    existing = todo / "root.txt"
    existing.write_bytes(b"original pending generation")
    assert queue.recover_running_to_todo([str(item)]) == 0
    assert running.read_bytes() == b"running generation"
    assert existing.read_bytes() == b"original pending generation"
    assert summarize_queue_observations(item)["observed_requeues"] == 0


def test_nested_recovery_preserves_preexisting_nested_todo(tmp_path):
    item, running = _setup_running(tmp_path, b"nested running", nested="stage")
    target = item / "TODO" / "stage" / "root.txt"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"nested existing TODO")
    assert queue.recover_running_to_todo([str(item)]) == 0
    assert running.read_bytes() == b"nested running"
    assert target.read_bytes() == b"nested existing TODO"


def test_normal_nested_recovery_preserves_path_and_emits_one_event(tmp_path):
    item, running = _setup_running(tmp_path, b"private nested", nested="stage")
    assert queue.recover_running_to_todo([str(item)]) == 1
    restored = item / "TODO" / "stage" / "root.txt"
    assert restored.read_bytes() == b"private nested"
    assert not running.exists()
    assert summarize_queue_observations(item)["observed_requeues"] == 1


def test_recovery_refuses_hardlink_unsupported_without_deleting_source(tmp_path, monkeypatch):
    item, running = _setup_running(tmp_path)
    original = queue.os.link
    def refuse(*_a, **_k):
        raise OSError("unsupported filesystem")
    monkeypatch.setattr(queue.os, "link", refuse)
    assert queue.recover_running_to_todo([str(item)]) == 0
    assert running.exists() and running.read_bytes() == b"running private input"
    assert not (item / "TODO" / "root.txt").exists()
    monkeypatch.setattr(queue.os, "link", original)


def test_existing_todo_symlink_is_never_overwritten(tmp_path):
    item, running = _setup_running(tmp_path)
    todo = item / "TODO"
    todo.mkdir()
    protected = tmp_path / "protected.txt"
    protected.write_bytes(b"outside protected")
    target = todo / "root.txt"
    try:
        target.symlink_to(protected)
    except (OSError, NotImplementedError):
        pytest.skip("symlink unavailable")
    assert queue.recover_running_to_todo([str(item)]) == 0
    assert target.is_symlink() and protected.read_bytes() == b"outside protected"
    assert running.exists()


def test_recovery_source_unlink_failure_leaves_both_links_not_reported(tmp_path, monkeypatch):
    item, running = _setup_running(tmp_path)
    original = Path.unlink
    def refuse_source(self, *args, **kwargs):
        if self == running:
            raise PermissionError("interrupted source unlink")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", refuse_source)
    assert queue.recover_running_to_todo([str(item)]) == 0
    todo = item / "TODO" / "root.txt"
    assert running.read_bytes() == todo.read_bytes() == b"running private input"
    assert summarize_queue_observations(item)["observed_requeues"] == 0
    # Because the source has two links, further retry cannot count it again.
    assert queue.recover_running_to_todo([str(item)]) == 0


def test_success_exists_blocks_fresh_claim_and_preserves_both_generations(tmp_path):
    item = tmp_path / "item"
    todo = item / "TODO"
    success = item / "Success"
    todo.mkdir(parents=True)
    success.mkdir()
    source = todo / "root.txt"
    target = success / "root.txt"
    source.write_bytes(b"fresh prompt")
    target.write_bytes(b"old completed result")
    assert queue.pick_and_claim_next_prompts([str(item)]) == []
    assert source.read_bytes() == b"fresh prompt"
    assert target.read_bytes() == b"old completed result"
    assert not (item / "RUNNING" / "root.txt").exists()


def test_success_writer_refuses_existing_output_without_modification(tmp_path):
    dest = tmp_path / "Success" / "root.txt"
    dest.parent.mkdir()
    dest.write_bytes(b"prior completed output")
    with pytest.raises(FileExistsError):
        queue.publish_success_text_no_clobber(str(dest), "new incompatible answer")
    assert dest.read_bytes() == b"prior completed output"
    assert list(dest.parent.glob(".success-*.tmp")) == []


def test_success_writer_atomic_winner_under_real_threads(tmp_path):
    dest = tmp_path / "Success" / "root.txt"
    dest.parent.mkdir()
    def publish(value):
        try:
            queue.publish_success_text_no_clobber(str(dest), value)
            return "published"
        except FileExistsError:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(publish, ("candidate A", "candidate B")))
    assert sorted(outcomes) == ["conflict", "published"]
    assert dest.read_text() in {"candidate A", "candidate B"}
    assert list(dest.parent.glob(".success-*.tmp")) == []


def _worker(monkeypatch, tmp, running, text):
    worker = pc.PromptAPIPipeline.__new__(pc.PromptAPIPipeline)
    worker.task, worker.content, worker.promptFile = "plain task", text, str(running)
    worker.OutputSaveFN = str(running.parent.parent / "Success" / running.name)
    worker.removeFinPromptFile = True
    worker.max_tokens, worker.allow_to_retry, worker.include_think = 1024, True, False
    worker.debug_print_llm_io, worker.debug_print_max_chars = False, 80
    worker.audit_path, worker.audit_run_id, worker.audit_prompt_tokens = (
        str(tmp / "audit.csv"), "run", {},
    )
    worker.PGMSubDir = str(tmp)
    worker.model_spec = {"base_url": ["http://offline.invalid"], "model_name": "isolated-model", "num_ctx": 2048}
    monkeypatch.setattr(pc, "select_idle_ollama_url", lambda *_a, **_k: "http://offline.invalid")
    monkeypatch.setattr(pc, "release_url_load", lambda *_a, **_k: None)
    return worker


def _response(text):
    return SimpleNamespace(
        usage=SimpleNamespace(completion_tokens=1),
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
    )


def test_real_worker_success_persists_output_and_removes_running(monkeypatch, tmp_path):
    item, running = _setup_running(tmp_path, b"real private prompt")
    w = _worker(monkeypatch, tmp_path, running, "real private prompt")
    monkeypatch.setattr(pc, "CallLLMAPI", lambda *_a, **_k: (_response("new output"), 0))
    result = w.proc()
    success = item / "Success" / "root.txt"
    assert result["ok"] and success.read_text() == "new output"
    assert not running.exists()


def test_real_worker_conflicting_success_preserves_running_and_prior_output(monkeypatch, tmp_path):
    item, running = _setup_running(tmp_path, b"real private prompt")
    success = item / "Success" / "root.txt"
    success.parent.mkdir()
    success.write_bytes(b"old verified output")
    w = _worker(monkeypatch, tmp_path, running, "real private prompt")
    monkeypatch.setattr(pc, "CallLLMAPI", lambda *_a, **_k: (_response("new output"), 0))
    w.proc()
    assert success.read_bytes() == b"old verified output"
    assert running.read_bytes() == b"real private prompt"
    assert list(success.parent.glob(".success-*.tmp")) == []
