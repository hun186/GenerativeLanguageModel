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
    # Recreate the header before queue_claim_event_id and the later
    # append-only finish_reason field were introduced.
    previous_fields = mod._FIELDS[:-2]
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


def test_duplicate_nested_todo_names_are_deferred_without_clobber(tmp_path):
    """Two same-basename TODO files must remain intact until disambiguated."""
    item = tmp_path / "item"
    for part in ("a", "b"):
        directory = item / "TODO" / part
        directory.mkdir(parents=True)
        (directory / "root.txt").write_text("original " + part, encoding="utf-8")
    received = {}
    batch = pick_and_claim_next_prompts([str(item)], claim_ids_out=received)
    assert batch == [] and received == {}
    assert not (item / "RUNNING" / "root.txt").exists()
    assert (item / "TODO" / "a" / "root.txt").read_text() == "original a"
    assert (item / "TODO" / "b" / "root.txt").read_text() == "original b"
    assert not (item / "_extract_slice_identity" / "queue_events").exists()


def test_duplicate_names_remain_intact_even_if_observer_is_broken(tmp_path, monkeypatch):
    from czjLLM.prompt_pipeline.runtime_support import prompt_queue as queue
    item = tmp_path / "item"
    for section in ("a", "b"):
        directory = item / "TODO" / section
        directory.mkdir(parents=True)
        (directory / "root.txt").write_text(section, encoding="utf-8")
    monkeypatch.setattr(queue, "record_queue_transition",
                        lambda *_a, **_k: (_ for _ in ()).throw(OSError("telemetry broken")))
    received = {}
    assert pick_and_claim_next_prompts([str(item)], claim_ids_out=received) == []
    assert received == {}
    assert (item / "TODO" / "a" / "root.txt").read_text() == "a"
    assert (item / "TODO" / "b" / "root.txt").read_text() == "b"


from czjLLM.prompt_pipeline.json_source_queue import (
    generated_source_handoff, finalize_generated_source_handoff,
    take_claimed_source_receipt, source_task_fingerprint,
)
from czjLLM.prompt_pipeline.runtime_support.load_meter import ItemsRegistry
from czjLLM.utilities.json_rule_policy import (
    receipt_for_trusted_appended_source, verified_source_span,
)


def _fresh_source_row(tmp_path, monkeypatch):
    from czjLLM.prompt_pipeline.prompt_generator import PromptGenerator, taskSetting
    name = "InfoExtraction-MultiDim-SQLFriendly-to json format"
    spec = dict(taskSetting[name], json_rule_repair={"multidim_evidence_quotes": True},
                json_rule_slice_contract="multidim_event_slice_v1")
    monkeypatch.setitem(taskSetting, name, spec)
    task_sha = source_task_fingerprint(name, taskSetting)
    assert len(task_sha) == 64
    source = 'original\n☆下列為輸入任務文本：\n他说"甲"。'
    prompt, span = PromptGenerator(SimpleNamespace(
        task=name, main_file_name="sample", think_mode=True,
        model_spec_name="qwen3.8",
    )).build_with_source_receipt(source)
    item = tmp_path / "row"
    todo = item / "TODO"
    todo.mkdir(parents=True)
    path = todo / "root.txt"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(prompt)
        pending = generated_source_handoff(path, stream, prompt, span, task_sha)
    record = finalize_generated_source_handoff(pending, path)
    assert record is not None and source not in record.wire
    registry = ItemsRegistry()
    registry.add(str(item), 1, "source.txt", "combined.txt",
                 source_handoffs={path.name: record})
    return item, path, source, prompt, registry, name, taskSetting


def test_source_handoff_actual_queue_claim_is_one_shot(tmp_path, monkeypatch):
    item, path, source, prompt, registry, task, pool = _fresh_source_row(tmp_path, monkeypatch)
    assert "source_handoffs" not in registry.list_items()[str(item)]
    claims = {}
    pairs = pick_and_claim_next_prompts([str(item)], claim_ids_out=claims, source_receipt_registry=registry)
    running = pairs[0][0]
    receipt = take_claimed_source_receipt(registry, str(item), running, claims[running], task, pool)
    assert verified_source_span(prompt, receipt) == source
    assert take_claimed_source_receipt(registry, str(item), running, claims[running], task, pool) is None
    assert recover_running_to_todo([str(item)]) == 1
    claims = {}
    pairs = pick_and_claim_next_prompts([str(item)], claim_ids_out=claims, source_receipt_registry=registry)
    running = pairs[0][0]
    assert take_claimed_source_receipt(registry, str(item), running, claims[running], task, pool) is None


@pytest.mark.parametrize("change", ["wrong_claim", "different_task", "same_text_new_inode", "changed_text"])
def test_source_handoff_refuses_mismatch_and_consumes_record(tmp_path, monkeypatch, change):
    item, path, source, prompt, registry, task, pool = _fresh_source_row(tmp_path, monkeypatch)
    if change == "same_text_new_inode":
        # Retain the old inode so identical replacement cannot reuse it.
        path.rename(item / "old.txt")
        path.write_text(prompt, encoding="utf-8")
    elif change == "changed_text":
        path.write_text(prompt + "changed", encoding="utf-8")
    claims = {}
    pairs = pick_and_claim_next_prompts([str(item)], claim_ids_out=claims, source_receipt_registry=registry)
    running = pairs[0][0]
    expected = claims[running]
    supplied = uuid4().hex if change == "wrong_claim" else expected
    supplied_task = "other task" if change == "different_task" else task
    assert take_claimed_source_receipt(registry, str(item), running, supplied, supplied_task, pool) is None
    assert take_claimed_source_receipt(registry, str(item), running, expected, task, pool) is None


def test_registry_replacement_or_removal_discards_source_handoff(tmp_path, monkeypatch):
    item, path, source, prompt, registry, task, pool = _fresh_source_row(tmp_path, monkeypatch)
    registry.add(str(item), 2, "new.txt", "new-result.txt")
    assert registry.take_source_handoff(str(item), path.name) is None
    registry.add(str(item), 2, "new.txt", "new-result.txt", source_handoffs={"root.txt": object()})
    registry.remove(str(item))
    assert registry.take_source_handoff(str(item), path.name) is None


def test_source_handoff_wired_only_to_actual_legacy_consumer_paths():
    source = Path("czjLLM/prompt_pipeline/pipeline_controller.py").read_text(encoding="utf-8")
    assert source.count("json_rule_source_receipt=take_claimed_source_receipt(") == 2
    assert "json_rule_source_receipt=take_claimed_source_receipt(" not in source[
        source.index("def call_llm_api("):source.index("class PromptAPIPipeline:")
    ]


@pytest.mark.parametrize("use_stale_claim", [True, False])
def test_recovery_before_worker_handoff_cannot_inherit_first_claim(tmp_path, monkeypatch, use_stale_claim):
    item, path, source, prompt, registry, task, pool = _fresh_source_row(tmp_path, monkeypatch)
    first = {}
    pairs = pick_and_claim_next_prompts([str(item)], claim_ids_out=first, source_receipt_registry=registry)
    running = pairs[0][0]
    assert recover_running_to_todo([str(item)]) == 1
    second = {}
    pairs = pick_and_claim_next_prompts([str(item)], claim_ids_out=second, source_receipt_registry=registry)
    assert pairs[0][0] == running and first[running] != second[running]
    supplied = first[running] if use_stale_claim else second[running]
    assert take_claimed_source_receipt(registry, str(item), running, supplied, task, pool) is None


def test_source_receipt_discarded_when_claim_observation_fails(tmp_path, monkeypatch):
    from czjLLM.prompt_pipeline.runtime_support import prompt_queue as queue
    item, path, source, prompt, registry, task, pool = _fresh_source_row(tmp_path, monkeypatch)
    with monkeypatch.context() as patch:
        patch.setattr(queue, "record_queue_transition", lambda *a, **kw: False)
        claims = {}
        pairs = pick_and_claim_next_prompts([str(item)], claim_ids_out=claims, source_receipt_registry=registry)
        assert len(pairs) == 1 and claims == {}
    assert recover_running_to_todo([str(item)]) == 1
    claims = {}
    pairs = pick_and_claim_next_prompts([str(item)], claim_ids_out=claims, source_receipt_registry=registry)
    running = pairs[0][0]
    assert take_claimed_source_receipt(registry, str(item), running, claims[running], task, pool) is None
