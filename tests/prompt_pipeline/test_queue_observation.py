"""Real filesystem TODO/RUNNING transition observation tests; no LLM provider."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from czjLLM.prompt_pipeline.runtime_support import prompt_queue as queue
from czjLLM.prompt_pipeline.runtime_support.queue_observation import (
    record_queue_transition, summarize_queue_observations,
)


def _todo(tmp_path, text="private prompt with sensitive words"):
    item = tmp_path / "item"
    todo = item / "TODO"
    todo.mkdir(parents=True, exist_ok=True)
    path = todo / "original.txt"
    path.write_text(text, encoding="utf-8")
    return item, path


def _events(item):
    directory = item / "_extract_slice_identity" / "queue_events"
    return sorted(directory.glob("*.json")) if directory.exists() else []


def test_actual_claim_and_requeue_have_distinct_persisted_event_ids(tmp_path):
    item, source = _todo(tmp_path)
    assert summarize_queue_observations(item) == {
        "observed_claims": 0, "observed_requeues": 0,
    }
    claimed = queue.pick_and_claim_next_prompts([str(item)])
    assert len(claimed) == 1
    running = Path(claimed[0][0])
    assert running.parent.name == "RUNNING" and running.exists()
    assert not source.exists()
    assert summarize_queue_observations(item) == {
        "observed_claims": 1, "observed_requeues": 0,
    }
    assert queue.recover_running_to_todo([str(item)]) == 1
    assert source.exists() and not running.exists()
    assert summarize_queue_observations(item) == {
        "observed_claims": 1, "observed_requeues": 1,
    }
    assert len(queue.pick_and_claim_next_prompts([str(item)])) == 1
    assert summarize_queue_observations(item) == {
        "observed_claims": 2, "observed_requeues": 1,
    }
    paths = _events(item)
    records = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    ids = [x["event_id"] for x in records]
    assert len(paths) == len(set(ids)) == 3
    assert all(p.stem == entry["event_id"] for p, entry in zip(paths, records))
    assert {entry["source_sha256"] for entry in records} == {
        records[0]["source_sha256"]
    }
    assert all(entry["queue_name_sha256"] for entry in records)
    # Hashes/opaque UUIDs only; no prompt, local pathname or LLM response.
    raw = "\n".join(p.read_text(encoding="utf-8") for p in paths)
    assert "private prompt" not in raw
    assert "original.txt" not in raw
    assert str(tmp_path) not in raw
    assert "worker_call_id" not in raw and "split_family_id" not in raw


def test_unobserved_plain_rename_cannot_fabricate_audit(tmp_path):
    item, source = _todo(tmp_path)
    running = item / "RUNNING" / source.name
    running.parent.mkdir()
    os.replace(source, running)
    assert summarize_queue_observations(item)["observed_claims"] == 0
    assert record_queue_transition(running, "claimed", previous_path=source)
    assert summarize_queue_observations(item)["observed_claims"] == 1
    assert not record_queue_transition(running, "requeued", previous_path=source)
    assert summarize_queue_observations(item)["observed_requeues"] == 0


def test_claim_recording_failure_does_not_prevent_real_dispatch(tmp_path, monkeypatch):
    item, source = _todo(tmp_path)
    monkeypatch.setattr(queue, "record_queue_transition",
                        lambda *_a, **_k: (_ for _ in ()).throw(OSError("disk full")))
    claimed = queue.pick_and_claim_next_prompts([str(item)])
    assert len(claimed) == 1 and Path(claimed[0][0]).exists()
    assert not source.exists()
    assert summarize_queue_observations(item)["observed_claims"] == 0
    assert queue.recover_running_to_todo([str(item)]) == 1
    assert source.exists()


def test_unmoved_source_or_invalid_queue_position_is_not_evidence(tmp_path):
    item, source = _todo(tmp_path)
    assert not record_queue_transition(source, "claimed")
    assert not record_queue_transition(item / "RUNNING" / "missing.txt", "claimed")
    assert not record_queue_transition(source, "requeued")
    assert not _events(item)
    with pytest.raises(ValueError, match="invalid queue transition"):
        record_queue_transition(source, "unknown")


def test_rename_failure_has_no_event(tmp_path, monkeypatch):
    item, source = _todo(tmp_path)
    real_replace = queue.os.replace
    def no_rename(*_a, **_k):
        raise PermissionError("no queue rename")
    monkeypatch.setattr(queue.os, "replace", no_rename)
    assert queue.pick_and_claim_next_prompts([str(item)]) == []
    assert source.exists() and not _events(item)
    monkeypatch.setattr(queue.os, "replace", real_replace)


def test_observations_do_not_infer_family_for_regenerated_source(tmp_path):
    item, original = _todo(tmp_path, "first source bytes")
    assert len(queue.pick_and_claim_next_prompts([str(item)])) == 1
    (item / "RUNNING" / original.name).unlink()
    original.write_text("new source bytes", encoding="utf-8")
    assert len(queue.pick_and_claim_next_prompts([str(item)])) == 1
    records = [json.loads(p.read_text(encoding="utf-8")) for p in _events(item)]
    assert len(records) == 2
    assert records[0]["event_id"] != records[1]["event_id"]
    assert records[0]["source_sha256"] != records[1]["source_sha256"]
    assert all("retry_family_id" not in record for record in records)


def test_invalid_or_symlinked_event_files_fail_closed(tmp_path):
    item, _ = _todo(tmp_path)
    place = item / "_extract_slice_identity" / "queue_events"
    place.mkdir(parents=True)
    (place / "unexpected.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid queue observation"):
        summarize_queue_observations(item)
    (place / "unexpected.json").unlink()
    target = tmp_path / "sensitive-text"
    target.write_text("hidden", encoding="utf-8")
    try:
        (place / ("a" * 32 + ".json")).symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError, match="invalid queue observation"):
        summarize_queue_observations(item)
    assert target.read_text(encoding="utf-8") == "hidden"


def test_symlinked_namespace_refuses_publish_and_read(tmp_path):
    item, _ = _todo(tmp_path)
    running = item / "RUNNING"
    running.mkdir()
    p = running / "root.txt"
    p.write_text("secret", encoding="utf-8")
    identity = item / "_extract_slice_identity"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    try:
        identity.symlink_to(elsewhere, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    assert not record_queue_transition(p, "claimed")
    with pytest.raises(ValueError, match="aliased"):
        summarize_queue_observations(item)
    assert list(elsewhere.iterdir()) == []


def test_corrupt_observation_rejected_without_guessing_counts(tmp_path):
    item, original = _todo(tmp_path)
    queue.pick_and_claim_next_prompts([str(item)])
    entry = _events(item)[0]
    obj = json.loads(entry.read_text(encoding="utf-8"))
    obj["source_sha256"] = "not SHA256"
    entry.write_text(json.dumps(obj), encoding="utf-8")
    with pytest.raises(ValueError, match="schema"):
        summarize_queue_observations(item)
