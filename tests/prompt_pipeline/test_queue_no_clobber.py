"""Real-filesystem regressions for no-clobber TODO-to-RUNNING dispatch."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from czjLLM.prompt_pipeline.runtime_support import prompt_queue as queue
from czjLLM.prompt_pipeline.runtime_support.queue_observation import (
    summarize_queue_observations,
)


def _todo(item: Path, name: str, data: bytes) -> Path:
    todo = item / "TODO"
    todo.mkdir(parents=True, exist_ok=True)
    file = todo / name
    file.write_bytes(data)
    return file


def test_preexisting_running_destination_is_not_replaced(tmp_path):
    item = tmp_path / "item"
    source = _todo(item, "root.txt", b"private queued source")
    running = item / "RUNNING"
    running.mkdir()
    target = running / "root.txt"
    target.write_bytes(b"already running unique content")
    receipt = {}
    assert queue.pick_and_claim_next_prompts([str(item)], claim_ids_out=receipt) == []
    assert receipt == {}
    assert target.read_bytes() == b"already running unique content"
    assert source.read_bytes() == b"private queued source"
    assert summarize_queue_observations(item) == {
        "observed_claims": 0, "observed_requeues": 0
    }


def test_two_nested_todo_sources_with_same_name_are_never_claimed(tmp_path):
    item = tmp_path / "item"
    a = item / "TODO" / "first"
    b = item / "TODO" / "second"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    first, second = a / "reused.txt", b / "reused.txt"
    first.write_bytes(b"first original")
    second.write_bytes(b"second original")
    ids = {}
    assert queue.pick_and_claim_next_prompts([str(item)], claim_ids_out=ids) == []
    assert first.read_bytes() == b"first original"
    assert second.read_bytes() == b"second original"
    assert ids == {}
    assert not (item / "RUNNING" / "reused.txt").exists()
    assert summarize_queue_observations(item)["observed_claims"] == 0


def test_undisputed_source_retains_original_two_tuple_return_and_receipt(tmp_path):
    item = tmp_path / "item"
    source = _todo(item, "unique.txt", b"source to dispatch")
    ids = {}
    claimed = queue.pick_and_claim_next_prompts([str(item)], claim_ids_out=ids)
    running = item / "RUNNING" / "unique.txt"
    assert claimed == [(str(running), str(item))]
    assert not source.exists()
    assert running.read_bytes() == b"source to dispatch"
    assert len(ids) == 1 and ids[str(running)]
    assert summarize_queue_observations(item)["observed_claims"] == 1


def test_link_unsupported_fails_closed_without_renaming(tmp_path, monkeypatch):
    item = tmp_path / "item"
    source = _todo(item, "unique.txt", b"original")
    monkeypatch.setattr(queue.os, "link",
                        lambda *_a, **_k: (_ for _ in ()).throw(OSError("no hardlinks")))
    assert queue.pick_and_claim_next_prompts([str(item)]) == []
    assert source.read_bytes() == b"original"
    assert not (item / "RUNNING" / "unique.txt").exists()
    assert summarize_queue_observations(item)["observed_claims"] == 0


def test_unlink_failure_never_dispatches_or_emits_false_claim(tmp_path, monkeypatch):
    item = tmp_path / "item"
    source = _todo(item, "unique.txt", b"original")
    true_unlink = Path.unlink
    def fail_source_only(path, *args, **kwargs):
        if path == source:
            raise PermissionError("cannot remove TODO")
        return true_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", fail_source_only)
    assert queue.pick_and_claim_next_prompts([str(item)]) == []
    running = item / "RUNNING" / "unique.txt"
    assert source.read_bytes() == running.read_bytes() == b"original"
    assert not (item / "_extract_slice_identity" / "queue_events").exists()
    # Follow-up claim never overwrites the interrupted RUNNING destination.
    assert queue.pick_and_claim_next_prompts([str(item)]) == []
    assert running.read_bytes() == b"original"


def test_parallel_direct_competition_cannot_overwrite_running(tmp_path):
    item = tmp_path / "item"
    todo = item / "TODO"
    a, b = todo / "a", todo / "b"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    left, right = a / "same.txt", b / "same.txt"
    left.write_bytes(b"left")
    right.write_bytes(b"right")
    target = item / "RUNNING" / "same.txt"
    target.parent.mkdir()
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(
            lambda source: queue._claim_regular_source_no_clobber(source, target),
            (left, right),
        ))
    assert sorted(outcomes) == [False, True]
    assert target.read_bytes() in (b"left", b"right")
    assert sum(source.exists() for source in (left, right)) == 1
    assert {target.read_bytes(), (left if left.exists() else right).read_bytes()} == {
        b"left", b"right"
    }


def test_source_symlink_never_claimed_or_observed(tmp_path):
    item = tmp_path / "item"
    real = tmp_path / "outside.txt"
    real.write_bytes(b"private outside source")
    todo = item / "TODO"
    todo.mkdir(parents=True)
    link = todo / "alias.txt"
    try:
        link.symlink_to(real)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    assert queue.pick_and_claim_next_prompts([str(item)]) == []
    assert real.read_bytes() == b"private outside source"
    assert link.is_symlink()
    assert not (item / "RUNNING" / "alias.txt").exists()


def test_preexisting_running_symlink_not_followed_or_overwritten(tmp_path):
    item = tmp_path / "item"
    source = _todo(item, "root.txt", b"good queued text")
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"protected")
    running = item / "RUNNING"
    running.mkdir()
    target = running / "root.txt"
    try:
        target.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    assert queue.pick_and_claim_next_prompts([str(item)]) == []
    assert source.read_bytes() == b"good queued text"
    assert outside.read_bytes() == b"protected"
    assert target.is_symlink()


def test_stopped_producer_cannot_finalize_with_unclaimable_todo(tmp_path):
    item = tmp_path / "item"
    source = _todo(item, "root.txt", b"not dispatched")
    from czjLLM.prompt_pipeline.runtime_support.prompt_queue import (
        require_no_pending_todo_sources,
    )
    with pytest.raises(RuntimeError, match="undispatched TODO"):
        require_no_pending_todo_sources([str(item)])
    assert source.read_bytes() == b"not dispatched"
    source.unlink()
    require_no_pending_todo_sources([str(item)])


def test_consumer_uses_fail_closed_pending_guard_at_shutdown():
    import inspect
    from czjLLM.prompt_pipeline import pipeline_controller
    source = inspect.getsource(pipeline_controller.llm_stream_consumer)
    assert "require_no_pending_todo_sources(item_dirs)" in source
    guard = source.index("require_no_pending_todo_sources(item_dirs)")
    assert "break" in source[guard:guard + 180]


def test_real_stream_consumer_reports_blocked_queue_after_producer_done(
    monkeypatch, tmp_path
):
    """No SQL/ES server: exercise the real no-work consumer path."""
    import threading
    from types import SimpleNamespace
    from czjLLM.prompt_pipeline import pipeline_controller as pc

    item = tmp_path / "item"
    for section in ("a", "b"):
        sub = item / "TODO" / section
        sub.mkdir(parents=True)
        (sub / "same.txt").write_text(section, encoding="utf-8")

    producer_done = threading.Event()
    producer_done.set()
    blocked = threading.Event()
    ctx = SimpleNamespace(
        _producer_done_flag=producer_done,
        _queue_claim_blocked_event=blocked,
        stage_cfg=None,
        es_writeback_rules=[],
        sql_writeback_rules=[],
    )
    registry = SimpleNamespace(
        list_items=lambda: {str(item): {"pk": "item"}},
    )
    failures = []
    monkeypatch.setattr(pc, "resolve_pipeline_stages", lambda *_a, **_k: [])
    monkeypatch.setattr(pc, "_stage_cfg_declares_flow", lambda *_a, **_k: False)
    monkeypatch.setattr(pc, "meter_read", lambda *_a, **_k: {
        "queue": {"pending": 2, "running": 0},
    })
    monkeypatch.setattr(pc, "meter_update", lambda *_a, **_k: None)
    monkeypatch.setattr(pc, "_audit_consumer_orchestration_failure",
                        lambda _ctx, code: failures.append(code))
    monkeypatch.setattr(pc, "tlog", lambda *_a, **_k: None)
    monkeypatch.setattr(pc, "tlog_warn", lambda *_a, **_k: None)

    stop_event = threading.Event()  # teardown has NOT happened yet
    pc.llm_stream_consumer(
        ctx, registry, str(tmp_path / "meter"), stop_event,
        restart_event=threading.Event(), per_round_limit=5,
    )
    assert not stop_event.is_set()
    assert blocked.is_set()
    assert failures == ["CONSUMER_TERMINATED"]
    assert (item / "TODO" / "a" / "same.txt").read_text() == "a"
    assert (item / "TODO" / "b" / "same.txt").read_text() == "b"


def test_orchestrator_links_producer_done_and_blocked_failure_before_teardown():
    import inspect
    from czjLLM.sql_mode.runtime import orchestrator
    source = inspect.getsource(orchestrator.run_pipeline)
    assert source.index("ctx._producer_done_flag = producer_done_flag") < source.index(
        "start_workers(ctx"
    )
    assert "ctx._queue_claim_blocked_event = queue_claim_blocked_event" in source
    assert "if A and queue_claim_blocked_event.is_set():" in source
    assert "terminal_queue_claim_blocked = True" in source
    assert 'observer.emit("run_failed", {"reason": "unclaimable_queue_sources"})' in source
