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


def _run_fixture(tmp_path, monkeypatch, *, fail_without_success=False, split_parent=False):
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

        def proc(self):
            i = int(Path(self.promptFile).parents[1].name.split("_")[-1])
            if i == 0:
                slow_started.set()
                assert release_slow.wait(8), "slow Worker was not released"
            if i == 2:
                fast_refilled.set()
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
        registry=registry, thread=thread, outcomes=outcomes,
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
    assert "verifiable Success" in str(fixture.outcomes[0])
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
