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
