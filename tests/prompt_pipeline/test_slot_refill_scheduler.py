"""Offline slot-refill safety and real filesystem Queue Claim tests."""
import threading
import time
from pathlib import Path
from uuid import uuid4
import pytest
from czjLLM.prompt_pipeline.refill_scheduler import (
    ClaimedWork, RefillAborted, run_slot_refill,
)


def test_slow_first_work_does_not_block_new_claims():
    queue = iter(range(7))
    slow = threading.Event()
    started = threading.Event()
    third = threading.Event()
    seen, acknowledged, outcomes = [], [], []
    def claim():
        value = next(queue, None)
        if value is None:
            return None
        seen.append(value)
        return ClaimedWork(uuid4().hex, value)
    def run(value):
        if value == 0:
            started.set()
            assert slow.wait(4)
        if value == 2:
            third.set()
        return value * 10
    def coordinator():
        try:
            outcomes.append(run_slot_refill(
                claim_one=claim, run_worker=run,
                acknowledge=lambda rec, res: acknowledged.append((rec.item, res)),
                max_inflight=2, deadline_sec=6,
            ))
        except Exception as exc:
            outcomes.append(exc)
    thread = threading.Thread(target=coordinator, daemon=True)
    thread.start()
    try:
        assert started.wait(2)
        assert third.wait(3), "no head-of-line barrier allowed"
    finally:
        slow.set()
    thread.join(5)
    assert not thread.is_alive()
    assert len(outcomes) == 1 and not isinstance(outcomes[0], Exception)
    assert outcomes[0].claimed == outcomes[0].acknowledged == 7
    assert outcomes[0].max_inflight_observed == 2
    assert seen == list(range(7))
    assert sorted(acknowledged) == [(i, i * 10) for i in range(7)]


def test_duplicate_receipt_cannot_dispatch_twice():
    claims = iter([ClaimedWork("dup", 1), ClaimedWork("dup", 2)])
    executed = []
    with pytest.raises(ValueError, match="replayed claim"):
        run_slot_refill(
            claim_one=lambda: next(claims, None),
            run_worker=lambda i: executed.append(i) or i,
            acknowledge=lambda *_: None, max_inflight=2,
        )
    assert 2 not in executed


def test_result_ack_failure_drains_other_worker_and_never_replays():
    release = threading.Event()
    started = threading.Event()
    drained = threading.Event()
    seen = []
    claims = iter(range(3))
    def claim():
        value = next(claims, None)
        if value is None:
            return None
        seen.append(value)
        return ClaimedWork(uuid4().hex, value)
    def worker(value):
        if value == 0:
            started.set()
            try:
                assert release.wait(3)
            finally:
                drained.set()
        return value
    errors = []
    def coordinator():
        try:
            run_slot_refill(
                claim_one=claim, run_worker=worker,
                acknowledge=lambda rec, res: (
                    release.set(),
                    (_ for _ in ()).throw(RuntimeError("sink ACK not confirmed"))
                ) if rec.item == 1 else None,
                max_inflight=2, deadline_sec=4,
            )
        except Exception as exc:
            errors.append(exc)
    t = threading.Thread(target=coordinator, daemon=True)
    t.start()
    assert started.wait(2)
    t.join(1)
    release.set()
    t.join(4)
    assert not t.is_alive() and drained.is_set()
    assert errors and isinstance(errors[0], RuntimeError)
    assert seen == [0, 1]


def test_stop_prevents_new_claim_without_implicit_requeue():
    stop = threading.Event()
    seen = []
    def claim():
        i = len(seen)
        seen.append(i)
        return ClaimedWork(uuid4().hex, i)
    def work(x):
        stop.set()
        return x
    with pytest.raises(RefillAborted, match="stop_requested"):
        run_slot_refill(
            claim_one=claim, run_worker=work,
            acknowledge=lambda *_: None, max_inflight=1,
            stop_requested=stop.is_set,
        )
    assert seen == [0]


def test_virtual_slow_fast_barrier_vs_refill_makespan():
    # Deterministic scheduling arithmetic, not a timing benchmark.
    durations = [10, 1, 1, 1, 1, 1, 1, 1]
    batch = sum(max(durations[i:i+2]) for i in range(0, 8, 2))
    # Slot 1 runs the 10-unit straggler; slot 2 completes the 7 fast jobs.
    continuous = max(10, sum(durations[1:]))
    assert batch == 13 and continuous == 10


def test_real_queue_claim_and_no_clobber_fixture(tmp_path):
    from czjLLM.prompt_pipeline.runtime_support.prompt_queue import (
        pick_and_claim_next_prompts, publish_success_text_no_clobber,
    )
    from czjLLM.prompt_pipeline.runtime_support.queue_observation import (
        verified_claim_observation,
    )
    item = tmp_path / "item"
    todo, success = item / "TODO", item / "Success"
    todo.mkdir(parents=True)
    success.mkdir()
    for i in range(5):
        (todo / f"{i}.txt").write_text(f"source-{i}", encoding="utf-8")
    receipts = set()
    def claim():
        obs = {}
        batch = pick_and_claim_next_prompts(
            [str(item)], per_round_limit=1, claim_ids_out=obs,
        )
        if not batch:
            return None
        running = Path(batch[0][0])
        receipt = obs[str(running)]
        assert receipt and receipt not in receipts
        assert verified_claim_observation(running, receipt) == receipt
        receipts.add(receipt)
        return ClaimedWork(receipt, running)
    def worker(path):
        return path.read_text(encoding="utf-8").replace("source", "done")
    def ack(claim, result):
        target = success / claim.item.name
        publish_success_text_no_clobber(str(target), result)
        assert target.read_text(encoding="utf-8") == result
        claim.item.unlink()
    stats = run_slot_refill(
        claim_one=claim, run_worker=worker,
        acknowledge=ack, max_inflight=2, deadline_sec=15,
    )
    assert stats.claimed == stats.acknowledged == 5
    assert len(receipts) == 5
    assert not list(todo.glob("*.txt"))
    assert not list((item / "RUNNING").glob("*.txt"))
    assert len(list(success.glob("*.txt"))) == 5


def test_error_that_finishes_during_ack_blocks_new_claim():
    ack_open = threading.Event()
    failed = threading.Event()
    seq = iter(range(3))
    seen = []
    def claim():
        value = next(seq, None)
        if value is None:
            return None
        seen.append(value)
        return ClaimedWork(uuid4().hex, value)
    def worker(value):
        if value == 1:
            assert ack_open.wait(3)
            failed.set()
            raise RuntimeError("worker failed")
        return value
    def acknowledge(rec, result):
        if rec.item == 0:
            ack_open.set()
            assert failed.wait(3)
    with pytest.raises(RuntimeError, match="worker failed"):
        run_slot_refill(
            claim_one=claim, run_worker=worker,
            acknowledge=acknowledge, max_inflight=2, deadline_sec=4,
        )
    assert seen == [0, 1], "failed active Worker must be checked before refill"


def test_producer_final_publication_between_empty_peek_and_done():
    todo = []
    calls = [0]
    acknowledged = []
    def claim():
        calls[0] += 1
        return todo.pop(0) if todo else None
    def producer_done():
        if not todo and calls[0] == 1:
            todo.append(ClaimedWork(uuid4().hex, 17))
        return True
    result = run_slot_refill(
        claim_one=claim, run_worker=lambda i: i * 2,
        acknowledge=lambda rec, value: acknowledged.append((rec.item, value)),
        producer_done=producer_done, max_inflight=1,
        deadline_sec=4,
    )
    assert result.claimed == result.acknowledged == 1
    assert acknowledged == [(17, 34)]
    assert todo == []
