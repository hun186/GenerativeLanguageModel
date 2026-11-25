"""Windows live slot-refill Consumer integration, no remote LLM or sink."""
from pathlib import Path
from types import SimpleNamespace
import threading


from czjLLM.prompt_pipeline import pipeline_controller as pc
from czjLLM.prompt_pipeline.slice_identity import install_split_prompts
from czjLLM.prompt_pipeline.runtime_support.prompt_queue import (
    publish_success_text_no_clobber,
)


class _Registry:
    def __init__(self, items):
        self.items = items

    def list_items(self):
        return dict(self.items)


def _run_fixture(tmp_path, monkeypatch, *, fail_without_success=False, split_parent=False,
                 deadline_clock=None, transport_uncertain=False, changed_source=False):
    slow_started = threading.Event()
    fast_refilled = threading.Event()
    release_slow = threading.Event()
    meter_lock = threading.Lock()
    item_dirs = {}
    for index in range(3):
        root = tmp_path / f"item_{index}"
        (root / "TODO").mkdir(parents=True)
        (root / "Success").mkdir()
        (root / "TODO" / "0.txt").write_text(f"input-{index}", encoding="utf-8")
        item_dirs[str(root)] = {"pk": str(index)}
    registry = _Registry(item_dirs)
    meter = {
        "queue": {"pending": 3, "running": 0, "completed": 0},
        "rows": {
            str(i): {"queue_pending": 1, "queue_running": 0, "done": 0, "total": 1}
            for i in range(3)
        },
    }

    def meter_update(_path, operation):
        with meter_lock:
            result = operation(meter)
            return meter if result is None else result

    class FakeJob:
        def __init__(self, **kwargs):
            self.promptFile = kwargs["promptFile"]
            self.OutputSaveFN = kwargs["OutputSaveFN"]
            self.content = Path(self.promptFile).read_text(encoding="utf-8")
            self.receipt = kwargs["queue_claim_event_id"]

        def proc(self):
            i = int(Path(self.promptFile).parents[1].name.split("_")[-1])
            if i == 0:
                slow_started.set()
                assert release_slow.wait(8), "slow Worker was not released"
            if i == 2:
                fast_refilled.set()
            if transport_uncertain and i == 1:
                if changed_source:
                    Path(self.promptFile).write_text("changed", encoding="utf-8")
                return {"ok": False, "output": "", "error": "fixture timeout",
                        "transport_uncertain_claim_id": self.receipt}
            if fail_without_success and i == 1:
                return {"ok": False, "error": "fixture"}
            if split_parent and i == 1 and Path(self.promptFile).stem == "0":
                install_split_prompts(
                    self.promptFile, self.content,
                    [("0-0.txt", "first-half"), ("0-1.txt", "second-half")],
                )
                Path(self.promptFile).unlink()
                return {"ok": False, "error": "JSON_OUTPUT_LIMIT_REACHED"}
            publish_success_text_no_clobber(self.OutputSaveFN, f"done-{i}")
            Path(self.promptFile).unlink()
            return {"ok": True}

    monkeypatch.setattr(pc, "PromptAPIPipeline", FakeJob)
    monkeypatch.setattr(pc, "meter_update", meter_update)
    monkeypatch.setattr(pc, "_llm_call_audit_kwargs", lambda ctx: {})
    context = SimpleNamespace(
        n_process=2, task="fixture", model_spec={}, max_tokens=10,
        PGMSubDir=str(tmp_path), removeFinPromptFile=True,
    )
    if deadline_clock is not None:
        context.n_process = 1
        context.llm_round_timeout_sec = 1
        from czjLLM.prompt_pipeline import refill_scheduler as scheduler
        monkeypatch.setattr(scheduler, "time", SimpleNamespace(monotonic=lambda: deadline_clock[0]))
    stop = threading.Event()
    receipts = {}
    first = pc.pick_and_claim_next_prompts(
        list(item_dirs), per_round_limit=1, claim_ids_out=receipts,
    )
    assert len(first) == 1 and receipts
    outcomes = []

    def run():
        try:
            outcomes.append(pc._run_windows_live_slot_refill(
                context, registry, str(tmp_path / "meter.json"),
                stop, threading.Event(), first=first[0],
                first_claim_ids=receipts,
                per_round_limit=5 if split_parent else 3,
            ))
        except BaseException as exc:
            outcomes.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return SimpleNamespace(
        slow_started=slow_started, fast_refilled=fast_refilled,
        release_slow=release_slow, meter=meter, meter_lock=meter_lock,
        registry=registry, thread=thread, outcomes=outcomes, context=context,
    )


def test_real_consumer_ack_and_refill_before_slow_worker(tmp_path, monkeypatch):
    fixture = _run_fixture(tmp_path, monkeypatch)
    try:
        assert fixture.slow_started.wait(4)
        assert fixture.fast_refilled.wait(5), (
            "fast worker must be acknowledged and its slot refilled "
            "while the first slow worker remains in-flight"
        )
        with fixture.meter_lock:
            assert fixture.meter["rows"]["1"]["done"] == 1
            assert fixture.meter["rows"]["1"]["queue_running"] == 0
            assert fixture.meter["rows"]["0"]["queue_running"] == 1
            assert fixture.meter["queue"]["completed"] >= 1
    finally:
        fixture.release_slow.set()
        fixture.thread.join(10)
    assert not fixture.thread.is_alive()
    assert len(fixture.outcomes) == 1
    stats = fixture.outcomes[0]
    assert not isinstance(stats, BaseException), repr(stats)
    assert (stats.claimed, stats.acknowledged, stats.max_inflight_observed) == (3, 3, 2)
    with fixture.meter_lock:
        assert fixture.meter["queue"] == {
            "pending": 0, "running": 0, "completed": 3,
        }
        assert all(row["queue_running"] == 0 and row["done"] == 1
                   for row in fixture.meter["rows"].values())
    for item in fixture.registry.items:
        assert (Path(item) / "Success" / "0.txt").is_file()


def test_worker_without_durable_success_never_gets_false_ack(tmp_path, monkeypatch):
    fixture = _run_fixture(tmp_path, monkeypatch, fail_without_success=True)
    try:
        assert fixture.slow_started.wait(4)
    finally:
        fixture.release_slow.set()
        fixture.thread.join(10)
    assert not fixture.thread.is_alive()
    assert len(fixture.outcomes) == 1
    assert isinstance(fixture.outcomes[0], RuntimeError)
    assert "unacknowledged RUNNING" in str(fixture.outcomes[0])
    with fixture.meter_lock:
        assert fixture.meter["rows"]["1"]["done"] == 0
        assert fixture.meter["rows"]["1"]["queue_running"] == 1
    assert (tmp_path / "item_1" / "RUNNING" / "0.txt").is_file()


def test_verified_split_parent_replaces_one_running_with_two_todo(tmp_path, monkeypatch):
    fixture = _run_fixture(tmp_path, monkeypatch, split_parent=True)
    try:
        assert fixture.slow_started.wait(4)
        assert fixture.fast_refilled.wait(5)
    finally:
        fixture.release_slow.set()
        fixture.thread.join(10)
    assert not fixture.thread.is_alive()
    assert len(fixture.outcomes) == 1
    stats = fixture.outcomes[0]
    assert not isinstance(stats, BaseException), repr(stats)
    assert (stats.claimed, stats.acknowledged) == (5, 5)
    with fixture.meter_lock:
        assert fixture.meter["queue"] == {
            "pending": 0, "running": 0, "completed": 4,
        }
        row = fixture.meter["rows"]["1"]
        assert (row["total"], row["done"], row["queue_pending"],
                row["queue_running"]) == (2, 2, 0, 0)
    assert not (tmp_path / "item_1" / "Success" / "0.txt").exists()
    assert (tmp_path / "item_1" / "Success" / "0-0.txt").is_file()
    assert (tmp_path / "item_1" / "Success" / "0-1.txt").is_file()


def test_split_publication_cannot_preempt_parent_meter_ack(tmp_path, monkeypatch):
    """Reproduce Codex P1: another Worker refills while split proc is in audit."""
    split_published = threading.Event()
    release_parent = threading.Event()
    independent_refilled = threading.Event()
    child_started_early = threading.Event()
    item_dirs = {}
    for i in range(3):
        root = tmp_path / f"item_{i}"
        (root / "TODO").mkdir(parents=True)
        (root / "Success").mkdir()
        (root / "TODO" / "0.txt").write_text(f"source-{i}", encoding="utf-8")
        item_dirs[str(root)] = {"pk": str(i)}
    registry = _Registry(item_dirs)
    meter_lock = threading.Lock()
    meter = {
        "queue": {"pending": 3, "running": 0, "completed": 0},
        "rows": {
            str(i): {"queue_pending": 1, "queue_running": 0, "done": 0, "total": 1}
            for i in range(3)
        },
    }

    def meter_update(_path, operation):
        with meter_lock:
            result = operation(meter)
            return meter if result is None else result

    class FakeJob:
        def __init__(self, **kwargs):
            self.promptFile = kwargs["promptFile"]
            self.OutputSaveFN = kwargs["OutputSaveFN"]
            self.content = Path(self.promptFile).read_text(encoding="utf-8")

        def proc(self):
            prompt = Path(self.promptFile)
            item_index = int(prompt.parents[1].name.split("_")[-1])
            if item_index == 0 and prompt.name == "0.txt":
                install_split_prompts(
                    self.promptFile, self.content,
                    [("0-0.txt", "left"), ("0-1.txt", "right")],
                )
                prompt.unlink()
                split_published.set()
                assert release_parent.wait(8), "parent audit was not released"
                return {"ok": False, "error": "JSON_OUTPUT_LIMIT_REACHED"}
            if item_index == 1:
                assert split_published.wait(4)
            if item_index == 2:
                independent_refilled.set()
            if item_index == 0 and prompt.name in {"0-0.txt", "0-1.txt"}:
                if not release_parent.is_set():
                    child_started_early.set()
            publish_success_text_no_clobber(self.OutputSaveFN, "done")
            prompt.unlink()
            return {"ok": True}

    monkeypatch.setattr(pc, "PromptAPIPipeline", FakeJob)
    monkeypatch.setattr(pc, "meter_update", meter_update)
    monkeypatch.setattr(pc, "_llm_call_audit_kwargs", lambda _ctx: {})
    ctx = SimpleNamespace(
        n_process=2, task="fixture", model_spec={}, max_tokens=10,
        PGMSubDir=str(tmp_path), removeFinPromptFile=True,
    )
    receipts = {}
    first = pc.pick_and_claim_next_prompts(
        list(item_dirs), per_round_limit=1, claim_ids_out=receipts,
    )
    assert len(first) == 1
    outcomes = []

    def coordinate():
        try:
            outcomes.append(pc._run_windows_live_slot_refill(
                ctx, registry, str(tmp_path / "meter.json"),
                threading.Event(), threading.Event(),
                first=first[0], first_claim_ids=receipts, per_round_limit=5,
            ))
        except BaseException as exc:
            outcomes.append(exc)

    runner = threading.Thread(target=coordinate, daemon=True)
    runner.start()
    try:
        assert split_published.wait(5)
        assert independent_refilled.wait(5), "unrelated TODO must still refill"
        assert not child_started_early.wait(0.2), (
            "split children dispatched before parent Worker returned and ACKed"
        )
        with meter_lock:
            assert meter["rows"]["0"]["queue_running"] == 1
            assert meter["rows"]["0"]["queue_pending"] == 0
    finally:
        release_parent.set()
        runner.join(10)
    assert not runner.is_alive()
    assert len(outcomes) == 1
    assert not isinstance(outcomes[0], BaseException), repr(outcomes[0])
    assert (outcomes[0].claimed, outcomes[0].acknowledged) == (5, 5)
    assert not child_started_early.is_set()
    with meter_lock:
        assert meter["queue"] == {"pending": 0, "running": 0, "completed": 4}
        assert meter["rows"]["0"]["total"] == meter["rows"]["0"]["done"] == 2
    assert (tmp_path / "item_0" / "Success" / "0-0.txt").exists()
    assert (tmp_path / "item_0" / "Success" / "0-1.txt").exists()


def test_live_deadline_drains_slow_worker_and_next_round_finishes_pending(tmp_path, monkeypatch):
    # Controlled clock: represent a >480-second LLM call without sleeping.
    clock = [0.0]
    fixture = _run_fixture(tmp_path, monkeypatch, deadline_clock=clock)
    try:
        assert fixture.slow_started.wait(4)
        clock[0] = 2.0
    finally:
        fixture.release_slow.set()
        fixture.thread.join(10)
    assert not fixture.thread.is_alive()
    assert len(fixture.outcomes) == 1
    stats = fixture.outcomes[0]
    assert not isinstance(stats, BaseException), repr(stats)
    assert stats.deadline_reached and stats.claimed == stats.acknowledged == 1
    assert fixture.meter["queue"] == {"pending": 2, "running": 0, "completed": 1}
    receipts = {}
    first = pc.pick_and_claim_next_prompts(list(fixture.registry.items),
                                         per_round_limit=1, claim_ids_out=receipts)
    assert len(first) == 1
    following = pc._run_windows_live_slot_refill(
        fixture.context, fixture.registry, str(tmp_path / "meter.json"),
        threading.Event(), threading.Event(), first=first[0],
        first_claim_ids=receipts, per_round_limit=2,
    )
    assert following.claimed == following.acknowledged == 2
    assert fixture.meter["queue"] == {"pending": 0, "running": 0, "completed": 3}
    for item in fixture.registry.items:
        assert (Path(item) / "Success" / "0.txt").is_file()
        assert not list((Path(item) / "RUNNING").glob("*.txt"))
        assert not list((Path(item) / "TODO").glob("*.txt"))


def test_verified_transport_uncertainty_holds_only_failed_row(tmp_path, monkeypatch):
    fixture = _run_fixture(tmp_path, monkeypatch, transport_uncertain=True)
    try:
        assert fixture.slow_started.wait(4)
        assert fixture.fast_refilled.wait(5), "healthy work must continue despite timeout"
    finally:
        fixture.release_slow.set()
        fixture.thread.join(10)
    assert not fixture.thread.is_alive()
    assert len(fixture.outcomes) == 1
    stats = fixture.outcomes[0]
    assert not isinstance(stats, BaseException), repr(stats)
    assert (stats.claimed, stats.acknowledged) == (3, 3)
    assert fixture.meter["queue"] == {"pending": 0, "running": 1, "completed": 2}
    assert fixture.meter["queue_integrity"]["held_running"] == 1
    assert fixture.meter["queue_integrity"]["status"] == "incomplete"
    assert fixture.meter["rows"]["1"]["done"] == 0
    assert fixture.meter["rows"]["1"]["queue_running"] == 1
    item = tmp_path / "item_1"
    assert (item / "RUNNING" / "0.txt").read_text(encoding="utf-8") == "input-1"
    assert not (item / "TODO" / "0.txt").exists()
    assert not (item / "Success" / "0.txt").exists()
    assert str(item) in pc._queue_recovery_blocked(fixture.context)
    marker = pc.read_recovery_status(str(item))
    assert marker["code"] == "WORKER_TRANSPORT_UNCERTAIN"
    assert marker["recheck_state"] == "operator_required"
    assert (tmp_path / "item_2" / "Success" / "0.txt").exists()


def test_transport_uncertainty_changed_claim_stays_fail_closed(tmp_path, monkeypatch):
    fixture = _run_fixture(tmp_path, monkeypatch, transport_uncertain=True, changed_source=True)
    try:
        assert fixture.slow_started.wait(4)
    finally:
        fixture.release_slow.set()
        fixture.thread.join(10)
    assert not fixture.thread.is_alive()
    assert isinstance(fixture.outcomes[0], RuntimeError)
    assert "unacknowledged RUNNING" in str(fixture.outcomes[0])
    assert fixture.meter["rows"]["1"]["done"] == 0
    assert pc.read_recovery_status(str(tmp_path / "item_1")) is None
