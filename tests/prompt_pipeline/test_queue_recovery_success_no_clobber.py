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


def test_interrupted_round_requeue_preserves_existing_todo(tmp_path):
    item, running = _setup_running(tmp_path, b"original running generation")
    existing = item / "TODO" / "root.txt"
    existing.parent.mkdir()
    existing.write_bytes(b"independent pending generation")
    assert queue.requeue_running_no_clobber(str(running)) is False
    assert running.read_bytes() == b"original running generation"
    assert existing.read_bytes() == b"independent pending generation"
    assert summarize_queue_observations(item)["observed_requeues"] == 0


def test_interrupted_round_requeue_records_only_completed_move(tmp_path):
    item, running = _setup_running(tmp_path, b"one interrupted batch")
    todo = item / "TODO" / "root.txt"
    assert queue.requeue_running_no_clobber(str(running)) is True
    assert todo.read_bytes() == b"one interrupted batch"
    assert not running.exists()
    assert summarize_queue_observations(item) == {
        "observed_claims": 0, "observed_requeues": 1,
    }


def test_interrupted_round_requeue_refuses_unsupported_link(tmp_path, monkeypatch):
    item, running = _setup_running(tmp_path, b"preserve original")
    monkeypatch.setattr(queue.os, "link",
                        lambda *_a, **_k: (_ for _ in ()).throw(
                            PermissionError("simulated unsupported hardlink")))
    assert queue.requeue_running_no_clobber(str(running)) is False
    assert running.read_bytes() == b"preserve original"
    assert not (item / "TODO" / "root.txt").exists()
    assert summarize_queue_observations(item)["observed_requeues"] == 0


def test_real_consumer_timeout_collision_is_terminal_without_overwrite(
    monkeypatch, tmp_path
):
    """Exercise actual picker, timeout handling, coordinator signal and files."""
    import threading

    item = tmp_path / "item"
    todo = item / "TODO" / "root.txt"
    todo.parent.mkdir(parents=True)
    todo.write_bytes(b"old dispatched generation")

    blocked, stopped = threading.Event(), threading.Event()
    ctx = SimpleNamespace(
        task=None, model_spec={}, PGMSubDir="", max_tokens=32,
        stage_cfg=None, es_writeback_rules=[], sql_writeback_rules=[],
        _queue_claim_blocked_event=blocked,
        mock_llm_mode=True,
    )
    registry = SimpleNamespace(list_items=lambda: {str(item): {"pk": "one"}})
    failures = []
    invoked = []

    monkeypatch.setattr(pc, "resolve_pipeline_stages", lambda *_a, **_k: [])
    monkeypatch.setattr(pc, "_stage_cfg_declares_flow", lambda *_a, **_k: False)
    monkeypatch.setattr(pc, "meter_update", lambda *_a, **_k: None)
    monkeypatch.setattr(pc, "_llm_call_audit_kwargs", lambda *_a, **_k: {})
    monkeypatch.setattr(pc, "PromptAPIPipeline", lambda **kw: SimpleNamespace(**kw))
    monkeypatch.setattr(pc, "_audit_consumer_orchestration_failure",
                        lambda _ctx, code: failures.append(code))
    monkeypatch.setattr(pc, "tlog", lambda *_a, **_k: None)
    monkeypatch.setattr(pc, "tlog_warn", lambda *_a, **_k: None)

    def timed_out_round(_ctx, jobs):
        assert len(jobs) == 1
        invoked.append("timed_out")
        # The independent new TODO arrives after the RUNNING claim,
        # while the original worker batch is still waiting for its timeout.
        todo.write_bytes(b"new pending generation")
        raise pc.BatchRunTimeout(1, 0, 1)

    monkeypatch.setattr(pc, "_run_legacy_leaf_round", timed_out_round)
    pc.llm_stream_consumer(ctx, registry, str(tmp_path / "meter"), stopped,
                           restart_event=threading.Event(), per_round_limit=1)

    running = item / "RUNNING" / "root.txt"
    assert invoked == ["timed_out"]
    assert blocked.is_set() and not stopped.is_set()
    assert running.read_bytes() == b"old dispatched generation"
    assert todo.read_bytes() == b"new pending generation"
    assert failures == ["CONSUMER_ROUND_TIMEOUT", "CONSUMER_TERMINATED"]
    assert summarize_queue_observations(item) == {
        "observed_claims": 1, "observed_requeues": 0,
    }


def test_strict_restart_recovery_blocks_collision_without_overwrite(tmp_path):
    item, running = _setup_running(tmp_path, b"older running source")
    target = item / "TODO" / "root.txt"
    target.parent.mkdir()
    target.write_bytes(b"fresh TODO from another producer")
    with pytest.raises(queue.QueueClaimRollbackError, match="recovery incomplete"):
        queue.recover_running_to_todo([str(item)], require_complete=True)
    assert target.read_bytes() == b"fresh TODO from another producer"
    assert running.read_bytes() == b"older running source"
    assert summarize_queue_observations(item)["observed_requeues"] == 0


def test_strict_restart_recovery_reports_partial_moves_and_blocks(tmp_path):
    item, _ = _setup_running(tmp_path, b"first source")
    running_dir = item / "RUNNING"
    second = running_dir / "second.txt"
    second.write_bytes(b"second source")
    existing = item / "TODO" / "second.txt"
    existing.parent.mkdir()
    existing.write_bytes(b"newer second source")
    with pytest.raises(queue.QueueClaimRollbackError):
        queue.recover_running_to_todo([str(item)], require_complete=True)
    # The first source may be moved before detecting the second collision;
    # no existing TODO may be overwritten and the caller must stop.
    assert existing.read_bytes() == b"newer second source"
    assert second.read_bytes() == b"second source"


@pytest.mark.parametrize("policy_call", [
    "_apply_resume_policy_multistage",
    "_apply_resume_policy_single_stage",
])
def test_full_restart_aborts_before_success_deletion_on_recovery_conflict(
    tmp_path, policy_call
):
    item, running = _setup_running(tmp_path, b"unrecovered source")
    todo = item / "TODO" / "root.txt"
    todo.parent.mkdir()
    todo.write_bytes(b"new TODO")
    success = item / "Success" / "root.txt"
    success.parent.mkdir()
    success.write_bytes(b"old successful output")
    fn = getattr(pc, policy_call)
    # The strict recovery guard must run before policy-specific cleanup.
    with pytest.raises(queue.QueueClaimRollbackError):
        fn("full_restart", [str(item)], ops=None)
    assert running.read_bytes() == b"unrecovered source"
    assert todo.read_bytes() == b"new TODO"
    assert success.read_bytes() == b"old successful output"


def test_consumer_restart_conflict_marks_terminal_block(tmp_path, monkeypatch):
    import threading

    item, running = _setup_running(tmp_path, b"running existing")
    todo = item / "TODO" / "root.txt"
    todo.parent.mkdir()
    todo.write_bytes(b"new pending")
    blocked, stop, restart = (threading.Event() for _ in range(3))
    restart.set()
    ctx = SimpleNamespace(
        stage_cfg=None, es_writeback_rules=[], sql_writeback_rules=[],
        _queue_claim_blocked_event=blocked,
    )
    registry = SimpleNamespace(list_items=lambda: {str(item): {"pk": "one"}})
    failures = []
    monkeypatch.setattr(pc, "resolve_pipeline_stages", lambda *_a, **_k: [])
    monkeypatch.setattr(pc, "_stage_cfg_declares_flow", lambda *_a, **_k: False)
    monkeypatch.setattr(pc, "meter_update", lambda *_a, **_k: None)
    monkeypatch.setattr(pc, "tlog", lambda *_a, **_k: None)
    monkeypatch.setattr(pc, "tlog_warn", lambda *_a, **_k: None)
    monkeypatch.setattr(pc, "_audit_consumer_orchestration_failure",
                        lambda _ctx, code: failures.append(code))

    pc.llm_stream_consumer(ctx, registry, str(tmp_path / "meter"), stop, restart)
    assert blocked.is_set()
    assert not stop.is_set() and not restart.is_set()
    assert failures == ["CONSUMER_TERMINATED"]
    assert todo.read_bytes() == b"new pending"
    assert running.read_bytes() == b"running existing"
    assert summarize_queue_observations(item)["observed_requeues"] == 0


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


def test_real_old_worker_completion_cannot_be_adopted_by_later_claim(
    tmp_path, monkeypatch
):
    """Reproduce Codex P1: old Worker publishes after first Success check.

    New claimant is paused immediately before the exclusive RUNNING move.
    Older Worker publishes its own Success and releases RUNNING. The claimant
    must then restore its TODO source and return NO new job or claim event.
    """
    import threading

    item, old_running = _setup_running(tmp_path, b"old source")
    todo = item / "TODO"
    todo.mkdir()
    fresh = todo / "root.txt"
    fresh.write_bytes(b"new generation never processed")
    started = threading.Event()
    resume = threading.Event()
    original_move = queue._claim_regular_source_no_clobber

    def pause_new_claim(source, target):
        if source == fresh and target == old_running:
            started.set()
            assert resume.wait(timeout=8), "claim test synchronization timed out"
        return original_move(source, target)

    monkeypatch.setattr(queue, "_claim_regular_source_no_clobber", pause_new_claim)
    monkeypatch.setattr(pc, "CallLLMAPI", lambda *_a, **_k: (_response("old result"), 0))
    original_worker = _worker(monkeypatch, tmp_path, old_running, "old source")
    receipts = {}
    with ThreadPoolExecutor(max_workers=1) as executor:
        claimed = executor.submit(
            queue.pick_and_claim_next_prompts, [str(item)],
            claim_ids_out=receipts,
        )
        try:
            assert started.wait(timeout=8)
            result = original_worker.proc()
            assert result["ok"] and not old_running.exists()
            assert (item / "Success" / "root.txt").read_text() == "old result"
        finally:
            resume.set()
        assert claimed.result(timeout=8) == []
    assert receipts == {}
    assert fresh.read_bytes() == b"new generation never processed"
    assert not old_running.exists()
    assert summarize_queue_observations(item)["observed_claims"] == 0


def test_cleanup_failure_after_committed_success_is_not_worker_failure(
    monkeypatch, tmp_path
):
    item, running = _setup_running(tmp_path, b"real prompt content")
    worker = _worker(monkeypatch, tmp_path, running, "real prompt content")
    monkeypatch.setattr(pc, "CallLLMAPI",
                        lambda *_a, **_k: (_response("actual completed result"), 0))
    original_unlink = Path.unlink
    seen = []

    def refuse_temporary_unlink(path, *args, **kwargs):
        if path.name.startswith(".success-") and path.suffix == ".tmp":
            seen.append(path.name)
            raise PermissionError("simulated staging cleanup failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", refuse_temporary_unlink)
    result = worker.proc()
    assert seen, "must simulate failure after actual Success publication"
    assert result["ok"] is True
    assert (item / "Success" / "root.txt").read_text() == "actual completed result"
    assert not running.exists(), "RUNNING may be removed only after Success committed"
    # A denied disposable cleanup leaves an orphan OUTSIDE Success, never
    # another input slice for the real item merger.
    staging = item / ".success-publish-staging"
    assert len(list(staging.glob(".success-*.tmp"))) == 1
    assert sorted((item / "Success").rglob("*")) == [item / "Success" / "root.txt"]
    from czjLLM.utilities.combine_utils import combine_api_finished_item
    combined_path = combine_api_finished_item(str(item), SimpleNamespace(
        task="plain response",
        mode="table",
        prompt_dir=str(tmp_path),
        temp_txt_finished_dir=str(tmp_path / "combined"),
        debug=True,
    ))
    # The actual merger adds one newline per slice. Assert there is only
    # one merged slice, not two duplicated payloads.
    assert Path(combined_path).read_text(encoding="utf-8") == "actual completed result\n"
    assert len(list(staging.glob(".success-*.tmp"))) == 1


def test_failed_publication_keeps_original_error_when_cleanup_fails(
    monkeypatch, tmp_path
):
    destination = tmp_path / "Success" / "root.txt"
    destination.parent.mkdir(parents=True)
    destination.write_text("original output", encoding="utf-8")
    original_unlink = Path.unlink
    def failed_cleanup(path, *args, **kwargs):
        if path.name.startswith(".success-") and path.suffix == ".tmp":
            raise PermissionError("cannot clean staged file")
        return original_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", failed_cleanup)
    with pytest.raises(FileExistsError):
        queue.publish_success_text_no_clobber(str(destination), "new output")
    assert destination.read_text(encoding="utf-8") == "original output"


def test_failed_claim_rollback_signals_coordinator_and_preserves_files(
    monkeypatch, tmp_path
):
    """Reproduce review P2 through the REAL consumer and file-based picker.

    An old Success arrives in the claim gap, while rolling fresh RUNNING
    back to TODO fails. The consumer must flag terminal queue failure for
    coordinator shutdown instead of disappearing while pending stays >0.
    """
    import threading
    from czjLLM.prompt_pipeline import pipeline_controller as pc
    from czjLLM.prompt_pipeline.runtime_support import prompt_queue as queue

    item, old_running = _setup_running(tmp_path, b"prior Worker source")
    pending = item / "TODO" / "root.txt"
    pending.parent.mkdir(parents=True)
    pending.write_bytes(b"fresh source must be retained")
    success = item / "Success" / "root.txt"

    actual_move = queue._claim_regular_source_no_clobber
    interleaving = []
    def move_with_failed_rollback(source, target):
        if source == pending and target == old_running:
            assert old_running.read_bytes() == b"prior Worker source"
            queue.publish_success_text_no_clobber(str(success), "old result")
            old_running.unlink()  # prior Worker finished while new claim waited
            interleaving.append("published_old_success")
            return actual_move(source, target)
        if source == old_running and target == pending:
            interleaving.append("rollback_denied")
            return False  # model permission error returning to original TODO
        return actual_move(source, target)

    monkeypatch.setattr(queue, "_claim_regular_source_no_clobber",
                        move_with_failed_rollback)

    producer_done, blocked, stopped = (threading.Event() for _ in range(3))
    producer_done.set()
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
    monkeypatch.setattr(pc, "meter_update", lambda *_a, **_k: None)
    monkeypatch.setattr(pc, "_audit_consumer_orchestration_failure",
                        lambda _ctx, code: failures.append(code))
    monkeypatch.setattr(pc, "tlog", lambda *_a, **_k: None)
    monkeypatch.setattr(pc, "tlog_warn", lambda *_a, **_k: None)

    pc.llm_stream_consumer(
        ctx, registry, str(tmp_path / "meter"), stopped,
        restart_event=threading.Event(), per_round_limit=4,
    )
    assert interleaving == ["published_old_success", "rollback_denied"]
    assert blocked.is_set(), "coordinator must observe unrecoverable queue error"
    assert producer_done.is_set() and not stopped.is_set()
    assert failures == ["CONSUMER_TERMINATED"]
    assert success.read_text(encoding="utf-8") == "old result"
    assert old_running.read_bytes() == b"fresh source must be retained"
    assert not pending.exists()
    assert summarize_queue_observations(item)["observed_claims"] == 0


def test_real_producer_exits_unfinished_drain_on_terminal_claim_failure(
    monkeypatch, tmp_path
):
    """Codex P2: producer pending/outstanding must not wait for hard timeout.

    This exercises the actual SQL/Table/ES produce_rows entry, rather than
    pre-setting the producer-done flag and skipping its drain loop.
    """
    import threading
    from czjLLM.sql_mode.runtime import producer as prod
    from czjLLM.prompt_pipeline import pipeline_controller as pc

    blocked = threading.Event()
    stop = threading.Event()
    ctx = SimpleNamespace(
        _queue_claim_blocked_event=blocked,
        producer_drain_soft=300.0,
        producer_drain_hard=600.0,
        mode="sql",
        on_premises=True,
    )
    progress = {}
    produced = []

    monkeypatch.setattr(prod, "order_rows_avoiding_running", lambda _ctx, rows: rows)
    monkeypatch.setattr(prod, "announce_pending_recheck_if_enabled", lambda _ctx: False)
    monkeypatch.setattr(prod, "finalize_scheduled", lambda *_a, **_k: None)
    monkeypatch.setattr(prod, "cap_orchestration_workers", lambda *_a, **_k: 1)
    monkeypatch.setattr(prod, "_stream_multistage_enabled", lambda _ctx: False)
    monkeypatch.setattr(prod, "still_pending_before_dispatch", lambda *_a, **_k: True)
    monkeypatch.setattr(prod, "mark_running", lambda *_a, **_k: None)
    monkeypatch.setattr(prod, "record_adjustment", lambda *_a, **_k: None)
    monkeypatch.setattr(prod, "tlog", lambda *_a, **_k: None)
    monkeypatch.setattr(prod, "tlog_warn", lambda *_a, **_k: None)
    monkeypatch.setattr(prod, "schedule_one_row",
                        lambda *_a, **_k: produced.append("sent") or 1)
    monkeypatch.setattr(prod, "producer_backpressure_wait", lambda **_k: None)

    def read_outstanding(_meter):
        # The actual Consumer would have raised QueueClaimRollbackError and
        # signaled the event while outstanding remains nonzero.
        blocked.set()
        return 5

    monkeypatch.setattr(prod, "outstanding_now", read_outstanding)
    def save_meter(_fn, change):
        d = {"progress": dict(progress)}
        change(d)
        progress.update(d.get("progress", {}))
        return d
    monkeypatch.setattr(prod, "meter_update", save_meter)

    results = []
    worker = threading.Thread(
        target=lambda: results.append(prod.produce_rows(
            ctx, [("row-1", "private input")],
            registry=SimpleNamespace(), meter_fn=str(tmp_path / "meter"),
            low=0, stop_event=stop, consumer=threading.current_thread(),
            p_sched=SimpleNamespace(update=lambda _n: None),
        )),
        daemon=True,
    )
    worker.start()
    worker.join(timeout=3)
    assert not worker.is_alive(), "producer deadlocked in outstanding drain"
    assert produced == ["sent"]
    assert results == [1]
    assert blocked.is_set() and not stop.is_set()
    assert progress["prod_done"] is False, "terminal failure is not normal drain"


def test_backpressure_wait_exits_on_terminal_rollback_without_cancel(
    monkeypatch, tmp_path
):
    """Keep producer stop/cancellation distinct from terminal queue failure."""
    import threading
    from czjLLM.prompt_pipeline import pipeline_controller as pc

    blocked, stop = threading.Event(), threading.Event()
    blocked.set()
    ctx = SimpleNamespace(_queue_claim_blocked_event=blocked)
    # A live thread would otherwise keep waiting for outstanding==low.
    monkeypatch.setattr(pc, "meter_read",
                        lambda *_a, **_k: {"queue": {"pending": 99, "running": 1}})
    result = []
    thread = threading.Thread(
        target=lambda: result.append(pc.producer_backpressure_wait(
            ctx, low=0, meter_fn=str(tmp_path / "meter"), stop_event=stop,
            consumer_thread=None, hard_timeout=600,
        )),
        daemon=True,
    )
    thread.start()
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert result == [None]
    assert blocked.is_set() and not stop.is_set()


def _blocked_success_consumer_fixture(monkeypatch, tmp_path, item):
    """Real consumer with unfinished producer and outstanding work remaining."""
    import threading
    from czjLLM.prompt_pipeline import pipeline_controller as pc

    producer_done, blocked, stop = (threading.Event() for _ in range(3))
    ctx = SimpleNamespace(
        _producer_done_flag=producer_done,  # intentionally NOT set
        _queue_claim_blocked_event=blocked,
        stage_cfg=None, es_writeback_rules=[], sql_writeback_rules=[],
    )
    registry = SimpleNamespace(list_items=lambda: {str(item): {"pk": "one"}})
    failures = []
    monkeypatch.setattr(pc, "resolve_pipeline_stages", lambda *_a, **_k: [])
    monkeypatch.setattr(pc, "_stage_cfg_declares_flow", lambda *_a, **_k: False)
    monkeypatch.setattr(pc, "meter_update", lambda *_a, **_k: None)
    monkeypatch.setattr(pc, "meter_read", lambda *_a, **_k: {
        "queue": {"pending": 20, "running": 3},
    })
    monkeypatch.setattr(pc, "_audit_consumer_orchestration_failure",
                        lambda _ctx, code: failures.append(code))
    monkeypatch.setattr(pc, "tlog", lambda *_a, **_k: None)
    monkeypatch.setattr(pc, "tlog_warn", lambda *_a, **_k: None)
    return ctx, registry, stop, failures


def test_preexisting_success_blocks_consumer_before_producer_done(
    monkeypatch, tmp_path
):
    item = tmp_path / "item"
    source = item / "TODO" / "root.txt"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"fresh source never consumed")
    target = item / "Success" / "root.txt"
    target.parent.mkdir()
    target.write_bytes(b"existing old output")
    ctx, registry, stop, failures = _blocked_success_consumer_fixture(
        monkeypatch, tmp_path, item,
    )
    pc.llm_stream_consumer(ctx, registry, str(tmp_path / "meter"), stop,
                           restart_event=None)
    assert ctx._queue_claim_blocked_event.is_set()
    assert not ctx._producer_done_flag.is_set() and not stop.is_set()
    assert failures == ["CONSUMER_TERMINATED"]
    assert source.read_bytes() == b"fresh source never consumed"
    assert target.read_bytes() == b"existing old output"


def test_successful_rollback_signals_before_producer_completion(
    monkeypatch, tmp_path
):
    """Old Worker publishes in claim gap; fresh source rolls back cleanly.

    Unlike failed-rollback handling, this must also signal the coordinator
    while the real Producer has outstanding work and has NOT yet finished.
    """
    item, old_running = _setup_running(tmp_path, b"prior worker source")
    source = item / "TODO" / "root.txt"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"new source to preserve")
    prior_output = item / "Success" / "root.txt"
    real_move = queue._claim_regular_source_no_clobber
    interleaving = []
    def concurrent_old_worker(source_path, target_path):
        if source_path == source and target_path == old_running:
            queue.publish_success_text_no_clobber(str(prior_output), "older output")
            old_running.unlink()
            interleaving.append("older_worker_published")
        if source_path == old_running and target_path == source:
            interleaving.append("fresh_rollback")
        return real_move(source_path, target_path)
    monkeypatch.setattr(queue, "_claim_regular_source_no_clobber",
                        concurrent_old_worker)
    ctx, registry, stop, failures = _blocked_success_consumer_fixture(
        monkeypatch, tmp_path, item,
    )
    pc.llm_stream_consumer(ctx, registry, str(tmp_path / "meter"), stop,
                           restart_event=None)
    assert interleaving == ["older_worker_published", "fresh_rollback"]
    assert ctx._queue_claim_blocked_event.is_set()
    assert not ctx._producer_done_flag.is_set() and not stop.is_set()
    assert failures == ["CONSUMER_TERMINATED"]
    assert source.read_bytes() == b"new source to preserve"
    assert prior_output.read_text() == "older output"
    assert not old_running.exists()
    assert summarize_queue_observations(item)["observed_claims"] == 0


def test_omitted_orphan_cleanup_never_enters_nested_success_tree(
    monkeypatch, tmp_path
):
    nested_output = tmp_path / "item" / "Success" / "stage" / "root.txt"
    original_unlink = Path.unlink
    def deny_cleanup(path, *args, **kwargs):
        if path.name.startswith(".success-") and path.suffix == ".tmp":
            raise PermissionError("staged artifact still open")
        return original_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", deny_cleanup)
    queue.publish_success_text_no_clobber(str(nested_output), "committed")
    assert nested_output.read_text() == "committed"
    assert len(list((tmp_path / "item" / ".success-publish-staging").glob(".success-*.tmp"))) == 1
    assert list((tmp_path / "item" / "Success").rglob("*.tmp")) == []


def test_repeated_success_ancestors_never_put_stage_inside_outer_success(
    tmp_path, monkeypatch
):
    """Codex P2: item/Success/Success/root.txt is one logical merge slice.

    Failure to delete a published staging hardlink must never leave another
    readable input anywhere under the OUTERMOST Success ancestor.
    """
    item = tmp_path / "item"
    output = item / "Success" / "Success" / "root.txt"
    original_unlink = Path.unlink
    def fail_stage_cleanup(path, *args, **kwargs):
        if path.name.startswith(".success-") and path.suffix == ".tmp":
            raise PermissionError("simulated orphan after committed publication")
        return original_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", fail_stage_cleanup)

    queue.publish_success_text_no_clobber(str(output), "one logical slice")
    outer = item / "Success"
    assert output.read_text(encoding="utf-8") == "one logical slice"
    assert len([p for p in outer.rglob("*") if p.is_file()]) == 1
    orphan_dir = item / ".success-publish-staging"
    assert len(list(orphan_dir.glob(".success-*.tmp"))) == 1
    assert not (outer / ".success-publish-staging").exists()

    from czjLLM.utilities.combine_utils import combine_api_finished_item
    result = combine_api_finished_item(str(item), SimpleNamespace(
        task="plain response",
        mode="table",
        prompt_dir=str(tmp_path),
        temp_txt_finished_dir=str(tmp_path / "combined"),
        debug=True,
    ))
    assert Path(result).read_text(encoding="utf-8") == "one logical slice\n"
    assert len(list(orphan_dir.glob(".success-*.tmp"))) == 1
