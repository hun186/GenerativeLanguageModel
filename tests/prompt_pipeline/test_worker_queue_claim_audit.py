"""Actual filesystem and isolated Worker call-site queue receipt correlation."""
import csv
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from czjLLM.prompt_pipeline import pipeline_controller as pc
from czjLLM.prompt_pipeline.runtime_support.prompt_queue import (
    pick_and_claim_next_prompts, recover_running_to_todo,
)
from czjLLM.prompt_pipeline.runtime_support.queue_observation import (
    verified_claim_observation,
)
from czjLLM.utilities.llm_call_audit import log_llm_call

def resp(text):
    return SimpleNamespace(
        usage=SimpleNamespace(completion_tokens=1),
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
    )


def worker(monkeypatch, tmp, path, text):
    w = pc.PromptAPIPipeline.__new__(pc.PromptAPIPipeline)
    w.task, w.content, w.promptFile = "plain task", text, str(path)
    w.OutputSaveFN, w.removeFinPromptFile = "", False
    w.max_tokens, w.allow_to_retry, w.include_think = 1024, True, False
    w.debug_print_llm_io, w.debug_print_max_chars = False, 80
    w.audit_path, w.audit_run_id, w.audit_prompt_tokens = str(tmp / "llm_call_audit_claim.csv"), "run", {}
    w.PGMSubDir = str(tmp)
    w.model_spec = {"base_url": ["http://offline.invalid"],
                    "model_name": "isolated-model", "num_ctx": 2048}
    monkeypatch.setattr(pc, "select_idle_ollama_url", lambda *_a, **_k: "http://offline.invalid")
    monkeypatch.setattr(pc, "release_url_load", lambda *_a, **_k: None)
    return w



def _actual_claim(tmp_path, text="private worker source"):
    item = tmp_path / "item"
    todo = item / "TODO"
    todo.mkdir(parents=True, exist_ok=True)
    source = todo / "root.txt"
    source.write_text(text, encoding="utf-8")
    receipts = {}
    pairs = pick_and_claim_next_prompts([str(item)], claim_ids_out=receipts)
    assert len(pairs) == 1
    running = Path(pairs[0][0])
    assert running.exists() and not source.exists()
    assert len(receipts) == 1
    return item, running, receipts[str(running)]


def _audit_rows(path):
    with open(path, newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_real_claim_id_is_handed_to_worker_and_persisted_with_worker_call(monkeypatch, tmp_path):
    item, running, receipt = _actual_claim(tmp_path)
    assert verified_claim_observation(running, receipt) == receipt
    w = worker(monkeypatch, tmp_path, running, "private worker source")
    w.queue_claim_event_id = receipt
    monkeypatch.setattr(pc, "CallLLMAPI", lambda *_a, **_k: (resp("ok"), 0))
    assert w.proc()["ok"]
    audit = _audit_rows(w.audit_path)
    assert len(audit) == 1
    row = audit[0]
    assert row["queue_claim_event_id"] == receipt
    assert len(row["worker_call_id"]) == 32
    assert row["call_llm_api_returned"] == "YES"
    assert row["split_family_id"] == ""
    assert row["audit_record_id"] != receipt
    with open(item / "_extract_slice_identity" / "queue_events" / (receipt + ".json"), encoding="utf-8") as fp:
        claim = json.load(fp)
    assert claim["event"] == "claimed" and claim["event_id"] == receipt


def test_explicit_claim_receipt_does_not_identify_provider_http_or_requeue_family(monkeypatch, tmp_path):
    item, running, receipt = _actual_claim(tmp_path)
    monkeypatch.setattr(pc, "CallLLMAPI", lambda *_a, **_k: (resp("done"), 0))
    w1 = worker(monkeypatch, tmp_path, running, "private worker source")
    w1.queue_claim_event_id = receipt
    assert w1.proc()["ok"]
    # Separate observed requeue and second claim are separate receipts.
    assert recover_running_to_todo([str(item)]) == 1
    receipts = {}
    assert len(pick_and_claim_next_prompts([str(item)], claim_ids_out=receipts)) == 1
    later = receipts[str(running)]
    assert receipt != later
    w2 = worker(monkeypatch, tmp_path, running, "private worker source")
    w2.queue_claim_event_id = later
    assert w2.proc()["ok"]
    rows = _audit_rows(w1.audit_path)
    assert len(rows) == 2
    assert [row["queue_claim_event_id"] for row in rows] == [receipt, later]
    assert rows[0]["worker_call_id"] != rows[1]["worker_call_id"]
    assert all("retry_family_id" not in row for row in rows)


def test_stale_or_mismatched_source_never_gets_claim_attribution(monkeypatch, tmp_path):
    _, running, receipt = _actual_claim(tmp_path, text="prior source")
    running.write_text("replacement different text", encoding="utf-8")
    assert verified_claim_observation(running, receipt) == ""
    w = worker(monkeypatch, tmp_path, running, "replacement different text")
    w.queue_claim_event_id = receipt
    monkeypatch.setattr(pc, "CallLLMAPI", lambda *_a, **_k: (resp("ok"), 0))
    assert w.proc()["ok"]
    assert _audit_rows(w.audit_path)[0]["queue_claim_event_id"] == ""


def test_no_implicit_claim_id_from_filename_hash_or_unverified_source(monkeypatch, tmp_path):
    _, running, receipt = _actual_claim(tmp_path, text="authentic prompt")
    monkeypatch.setattr(pc, "CallLLMAPI", lambda *_a, **_k: (resp("ok"), 0))
    w = worker(monkeypatch, tmp_path, running, "authentic prompt")
    assert w.proc()["ok"]
    assert _audit_rows(w.audit_path)[0]["queue_claim_event_id"] == ""
    # Same observed on-disk file, but the Worker is sent a different prompt.
    other = worker(monkeypatch, tmp_path, running, "not the source prompt")
    other.queue_claim_event_id = receipt
    other.proc()
    assert _audit_rows(w.audit_path)[1]["queue_claim_event_id"] == ""


def test_bad_receipt_or_modified_event_fails_closed(monkeypatch, tmp_path):
    item, running, receipt = _actual_claim(tmp_path)
    path = item / "_extract_slice_identity" / "queue_events" / (receipt + ".json")
    original = path.read_text(encoding="utf-8")
    for wrong in ("", uuid4().hex, "0" * 32, "A" * 32, 12):
        assert verified_claim_observation(running, wrong) == ""
    data = json.loads(original)
    data["event"] = "requeued"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert verified_claim_observation(running, receipt) == ""
    path.write_text(original, encoding="utf-8")
    assert verified_claim_observation(running, receipt) == receipt


@pytest.mark.parametrize("invalid", ["0" * 32, "A" * 32, "bad", None, 42])
def test_direct_audit_rejects_invalid_claim_ids_without_creating_file(tmp_path, invalid):
    audit = tmp_path / "llm_call_audit_claim.csv"
    with pytest.raises(ValueError, match="queue claim"):
        log_llm_call(
            audit_path=str(audit), run_id="x",
            worker_call_id=uuid4().hex,
            call_llm_api_returned=False,
            queue_claim_event_id=invalid,
            model_spec={"num_ctx": 2048},
        )
    assert not audit.exists()


def test_direct_audit_claim_requires_worker_invocation(tmp_path):
    audit = tmp_path / "llm_call_audit_claim.csv"
    for kwargs in ({"worker_call_id": ""}, {"worker_call_id": uuid4().hex, "call_llm_api_returned": None}):
        with pytest.raises(ValueError, match="queue claim"):
            log_llm_call(
                audit_path=str(audit), run_id="x",
                queue_claim_event_id=uuid4().hex,
                model_spec={"num_ctx": 2048},
                **kwargs,
            )
        assert not audit.exists()


def test_previous_exact_audit_header_is_append_compatible(tmp_path):
    from czjLLM.utilities import llm_call_audit as mod
    path = tmp_path / "llm_call_audit_legacy.csv"
    previous_fields = mod._FIELDS[:-1]
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.DictWriter(stream, fieldnames=previous_fields).writeheader()
    log_llm_call(audit_path=str(path), run_id="x", worker_call_id=uuid4().hex,
                 call_llm_api_returned=True, queue_claim_event_id=uuid4().hex,
                 model_spec={"num_ctx": 2048})
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        assert reader.fieldnames == previous_fields
    assert len(rows) == 1 and "queue_claim_event_id" not in rows[0]
