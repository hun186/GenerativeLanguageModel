"""Leaf worker exception phase observability without false provider attribution.

Calls real PromptAPIPipeline.proc with isolated external provider/audit stubs.
The production exception-to-result and per-request CSV contract is unchanged.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from czjLLM.prompt_pipeline import pipeline_controller as pc
from czjLLM.utilities.processing_quality import QualityTailReader, quality_event_path


def _make_worker(monkeypatch, tmp_path, *, task="plain task", saved=False, mock=False):
    worker = pc.PromptAPIPipeline.__new__(pc.PromptAPIPipeline)
    worker.task = task
    worker.content = "private raw input text"
    worker.promptFile = "private-source-prompt.txt"
    worker.OutputSaveFN = str(tmp_path / "Success" / "private-output.txt") if saved else ""
    worker.removeFinPromptFile = False
    worker.max_tokens = 4096
    worker.allow_to_retry = True
    worker.include_think = False
    worker.debug_print_llm_io = False
    worker.debug_print_max_chars = 120
    worker.audit_path = str(tmp_path / "llm_call_audit_worker.csv")
    worker.audit_run_id = "worker-quality-run"
    worker.audit_prompt_tokens = {}
    worker.PGMSubDir = str(tmp_path)
    worker.model_spec = {
        "base_url": ["http://private-model.invalid"],
        "model_name": "mock-validation" if mock else "test-model",
        "api_key": "private-secret",
    }
    csv_attempts = []
    monkeypatch.setattr(pc, "select_idle_ollama_url", lambda *_args, **_kwargs: "http://private-model.invalid")
    monkeypatch.setattr(pc, "release_url_load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pc, "log_llm_call", lambda **kw: csv_attempts.append(kw))
    return worker, csv_attempts


def _response(text="private provider result"):
    return SimpleNamespace(
        usage=SimpleNamespace(completion_tokens=1),
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
    )


def _events(worker):
    path = quality_event_path(worker.audit_path)
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def _assert_single_phase_event(worker, code):
    records = _events(worker)
    assert len(records) == 1
    rec = records[0]
    assert rec["event"] == "worker_phase_failure"
    assert rec["code"] == code
    assert rec["scope"] == "run"
    assert rec["document_id"] == rec["slice_id"] == ""
    assert rec["run_id"] == "worker-quality-run"
    raw = quality_event_path(worker.audit_path).read_text(encoding="utf-8")
    for private in ("private raw input", "private-source-prompt", "private-output",
                    "private-secret", "private-model.invalid", "private provider"):
        assert private not in raw
    stats = QualityTailReader(str(quality_event_path(worker.audit_path))).poll()[1]
    assert stats["worker_phase_failure_events"] == 1
    assert stats["error_codes"][code] == 1
    assert stats["documents_decided"] == 0
    assert stats["slice_validation_attempts"] == 0


def test_endpoint_selection_exception_is_precall_not_provider(monkeypatch, tmp_path):
    worker, csv = _make_worker(monkeypatch, tmp_path)
    monkeypatch.setattr(pc, "select_idle_ollama_url",
                        lambda *_a, **_kw: (_ for _ in ()).throw(OSError("private endpoint")))
    outcome = worker.proc()
    assert outcome["ok"] is False
    assert "private endpoint" in outcome["error"]
    assert csv == []  # no LLM request attempt
    _assert_single_phase_event(worker, "WORKER_PRECALL_EXCEPTION")


def test_call_llm_exception_is_call_site_not_inferred_http_cause(monkeypatch, tmp_path):
    worker, csv = _make_worker(monkeypatch, tmp_path)
    monkeypatch.setattr(pc, "CallLLMAPI",
                        lambda *_a, **_kw: (_ for _ in ()).throw(ConnectionError("private provider")))
    outcome = worker.proc()
    assert outcome["ok"] is False
    assert len(csv) == 1 and csv[0]["ok"] is False
    _assert_single_phase_event(worker, "WORKER_LLM_CALL_EXCEPTION")


def test_json_postprocessing_exception_is_response_phase(monkeypatch, tmp_path):
    worker, csv = _make_worker(monkeypatch, tmp_path, task="to json")
    monkeypatch.setattr(pc, "CallLLMAPI", lambda *_a, **_kw: (_response('{"ok":1}'), 1.0))
    monkeypatch.setattr(worker, "handle_json_output",
                        lambda *_a: (_ for _ in ()).throw(ValueError("private parsed content")))
    outcome = worker.proc()
    assert outcome["ok"] is False
    assert len(csv) == 1 and csv[0]["ok"] is False
    _assert_single_phase_event(worker, "WORKER_RESPONSE_EXCEPTION")


def test_success_output_save_exception_is_local_persistence_not_llm(monkeypatch, tmp_path):
    worker, csv = _make_worker(monkeypatch, tmp_path, saved=True)
    monkeypatch.setattr(pc, "CallLLMAPI", lambda *_a, **_kw: (_response(), 1.0))
    monkeypatch.setattr(pc, "MKDIR",
                        lambda *_a, **_kw: (_ for _ in ()).throw(OSError("private file path")))
    outcome = worker.proc()
    assert outcome["ok"] is False
    assert len(csv) == 1 and csv[0]["ok"] is False
    _assert_single_phase_event(worker, "WORKER_PERSIST_EXCEPTION")


def test_successful_worker_has_no_exception_incident(monkeypatch, tmp_path):
    worker, csv = _make_worker(monkeypatch, tmp_path)
    monkeypatch.setattr(pc, "CallLLMAPI", lambda *_a, **_kw: (_response(), 1.0))
    outcome = worker.proc()
    assert outcome["ok"] is True
    assert len(csv) == 1 and csv[0]["ok"] is True
    assert _events(worker) == []


def test_mock_only_io_exception_has_no_production_incident(monkeypatch, tmp_path):
    worker, csv = _make_worker(monkeypatch, tmp_path, saved=True, mock=True)
    monkeypatch.setattr(pc, "MKDIR",
                        lambda *_a, **_kw: (_ for _ in ()).throw(OSError("mock-only failure")))
    outcome = worker.proc()
    assert outcome["ok"] is False
    assert csv == []
    assert _events(worker) == []


def test_execution_cancelled_does_not_count_as_worker_failure(monkeypatch, tmp_path):
    worker, csv = _make_worker(monkeypatch, tmp_path)
    monkeypatch.setattr(pc, "CallLLMAPI",
                        lambda *_a, **_kw: (_ for _ in ()).throw(pc.ExecutionCancelled("user stop")))
    outcome = worker.proc()
    assert outcome["ok"] is False  # pre-existing proc catch behavior, unchanged
    assert len(csv) == 1
    assert _events(worker) == []


def test_quality_write_failure_does_not_override_original_worker_failure(monkeypatch, tmp_path):
    worker, csv = _make_worker(monkeypatch, tmp_path)
    monkeypatch.setattr(pc, "CallLLMAPI",
                        lambda *_a, **_kw: (_ for _ in ()).throw(ValueError("authoritative worker error")))
    monkeypatch.setattr(pc, "emit_quality_event",
                        lambda *_a, **_kw: (_ for _ in ()).throw(OSError("audit unavailable")))
    outcome = worker.proc()
    assert outcome["ok"] is False
    assert "authoritative worker error" in outcome["error"]
    assert len(csv) == 1 and csv[0]["ok"] is False
    assert _events(worker) == []


def test_typed_sdk_exceptions_are_a_single_worker_event_and_csv_row(monkeypatch, tmp_path):
    import httpx
    from openai import APITimeoutError, RateLimitError, APIStatusError
    from czjLLM.prompt_pipeline import llm_caller

    for label, error, expected in (
        ("timeout", APITimeoutError(request=httpx.Request("POST", "https://private.invalid")),
         "WORKER_LLM_TIMEOUT_EXCEPTION"),
        ("rate", RateLimitError("private", response=httpx.Response(
            429, request=httpx.Request("POST", "https://private.invalid")), body=None),
         "WORKER_LLM_RATE_LIMIT_EXCEPTION"),
        ("server", APIStatusError("private", response=httpx.Response(
            503, request=httpx.Request("POST", "https://private.invalid")), body=None),
         "WORKER_LLM_HTTP_SERVER_EXCEPTION"),
    ):
        case_dir = tmp_path / label
        case_dir.mkdir()
        worker, csv = _make_worker(monkeypatch, case_dir)
        def throw(*_a, _error=error, **_kw):
            raise _error
        monkeypatch.setattr(pc, "CallLLMAPI", throw)
        result = worker.proc()
        assert result["ok"] is False
        assert len(csv) == 1 and csv[0]["ok"] is False
        _assert_single_phase_event(worker, expected)


def test_non_sdk_exception_message_never_guesses_provider_source(monkeypatch, tmp_path):
    worker, csv = _make_worker(monkeypatch, tmp_path)
    monkeypatch.setattr(pc, "CallLLMAPI", lambda *_a, **_kw:
                        (_ for _ in ()).throw(RuntimeError(
                            "HTTP 503 rate limit ReadTimeout private password")))
    assert worker.proc()["ok"] is False
    assert len(csv) == 1
    _assert_single_phase_event(worker, "WORKER_LLM_CALL_EXCEPTION")


def test_classifier_exception_never_masks_worker_failure(monkeypatch, tmp_path):
    worker, csv = _make_worker(monkeypatch, tmp_path)
    monkeypatch.setattr(pc, "CallLLMAPI", lambda *_a, **_kw:
                        (_ for _ in ()).throw(ValueError("authoritative-private-error")))
    monkeypatch.setattr(pc, "classify_llm_call_exception", lambda _e:
                        (_ for _ in ()).throw(RuntimeError("broken classifier")))
    result = worker.proc()
    assert result["ok"] is False
    assert "authoritative-private-error" in result["error"]
    assert len(csv) == 1 and csv[0]["ok"] is False
    _assert_single_phase_event(worker, "WORKER_LLM_CALL_EXCEPTION")



def test_real_worker_keeps_its_own_lease_live_during_long_stubbed_call(monkeypatch, tmp_path):
    """Exercise the production Worker boundary without contacting any provider."""
    import time
    from czjLLM.infrastructure import ollama_lb

    worker, audit = _make_worker(monkeypatch, tmp_path)
    monkeypatch.setattr(pc, "select_idle_ollama_url", ollama_lb.select_idle_ollama_url)
    monkeypatch.setattr(pc, "release_url_load", ollama_lb.release_url_load)
    monkeypatch.setattr(pc, "maintain_url_load_lease", ollama_lb.maintain_url_load_lease)
    # The former 0.18s TTL / 0.34s sleep was scheduler-sensitive on
    # shared Hosted CI (heartbeat was 0.04s late). Use enough real-clock
    # headroom while still requiring an observable renewal during a call
    # that outlives its original lease expiry.
    monkeypatch.setattr(ollama_lb, "LEASE_SECS", 1.5)

    def slow_provider_stub(*args, **kwargs):
        lease_file = tmp_path / "logs" / "base_url_load.json"
        before = json.loads(lease_file.read_text(encoding="utf-8"))
        original_lease = before["http://private-model.invalid"]["leases"]
        assert len(original_lease) == 1
        initial_expiry = original_lease[0]
        # Slow provider exceeds the initial 1.5s TTL and should still have
        # one current, owner-linked lease after multiple renewal intervals.
        time.sleep(2.25)
        record = json.loads(lease_file.read_text(encoding="utf-8"))
        current = record["http://private-model.invalid"]["leases"]
        assert len(current) == 1
        assert current[0] > initial_expiry  # Prove renewal, not just existence.
        assert current[0] > time.time()  # Prove the renewed lease is still live.
        return _response(), 0.0

    monkeypatch.setattr(pc, "CallLLMAPI", slow_provider_stub)
    result = worker.proc()
    assert result["ok"] is True
    assert len(audit) == 1 and audit[0]["ok"] is True
    file = tmp_path / "logs" / "base_url_load.json"
    assert json.loads(file.read_text(encoding="utf-8"))["http://private-model.invalid"]["leases"] == []


def test_transport_uncertainty_receipt_requires_real_verified_claim(monkeypatch, tmp_path):
    import httpx
    from openai import APITimeoutError

    worker, csv = _make_worker(monkeypatch, tmp_path)
    item = tmp_path / "item"
    (item / "TODO").mkdir(parents=True)
    (item / "TODO" / "0.txt").write_text(worker.content, encoding="utf-8")
    receipts = {}
    claims = pc.pick_and_claim_next_prompts([str(item)], per_round_limit=1,
                                            claim_ids_out=receipts)
    worker.promptFile = claims[0][0]
    worker.queue_claim_event_id = receipts[worker.promptFile]
    def timeout(*a, **kw):
        try:
            raise APITimeoutError(request=httpx.Request("POST", "https://private.invalid"))
        except APITimeoutError as exc:
            raise RuntimeError("LLM_CALL_TIMEOUT_OR_CONN: Request timed out.") from exc
    monkeypatch.setattr(pc, "CallLLMAPI", timeout)
    result = worker.proc()
    assert result["ok"] is False
    assert result["transport_uncertain_claim_id"] == worker.queue_claim_event_id
    assert Path(worker.promptFile).is_file()
    assert len(csv) == 1 and csv[0]["ok"] is False
    _assert_single_phase_event(worker, "WORKER_LLM_TIMEOUT_EXCEPTION")
    monkeypatch.setattr(pc, "CallLLMAPI", lambda *a, **kw:
                        (_ for _ in ()).throw(RuntimeError("Request timed out.")))
    assert "transport_uncertain_claim_id" not in worker.proc()


def test_capped_worker_releases_endpoint_before_nested_json_repair(monkeypatch, tmp_path):
    """A synchronous repair can reacquire the same endpoint at cap=1."""
    from czjLLM.infrastructure import ollama_lb

    worker, audit = _make_worker(monkeypatch, tmp_path, task="to json")
    url = worker.model_spec["base_url"][0]
    worker.model_spec["max_concurrent_per_endpoint"] = 1
    # Use the real default load-file scope shared by json_format_caller.
    monkeypatch.chdir(tmp_path)
    worker.PGMSubDir = ""
    path = tmp_path / "logs" / "base_url_load.json"

    def select_now(*args, **kwargs):
        return ollama_lb.select_idle_ollama_url(
            *args, **kwargs, admission_timeout_sec=0,
        )

    monkeypatch.setattr(pc, "select_idle_ollama_url", select_now)
    monkeypatch.setattr(pc, "release_url_load", ollama_lb.release_url_load)
    calls = []

    def provider(*args, **kwargs):
        assert len(json.loads(path.read_text())[url]["leases"]) == 1
        calls.append(kwargs["model_spec"]["base_url"])
        return _response('{"a":1,}' if len(calls) == 1 else '{"a":1}'), 0.0

    def nested_repair(raw):
        assert raw == '{"a":1,}'
        assert json.loads(path.read_text())[url]["leases"] == []
        # A real nested PromptAPIPipeline.proc on the same endpoint, using
        # the default PGMSubDir and no provider/network access.
        child, _ = _make_worker_for_nested_repair(worker)
        result = child.proc()
        assert result["ok"]
        return [], result["output"]

    def _make_worker_for_nested_repair(parent):
        child = pc.PromptAPIPipeline.__new__(pc.PromptAPIPipeline)
        child.__dict__.update(parent.__dict__)
        child.model_spec = dict(parent.model_spec)
        child.task = "json format repair"
        child.promptFile = ""
        child.content = "synthetic repair prompt"
        child.allow_to_retry = False
        return child, None

    monkeypatch.setattr(pc, "CallLLMAPI", provider)
    monkeypatch.setattr(worker, "handle_json_output", nested_repair)
    result = worker.proc()
    assert result["ok"] and result["output"] == '{"a":1}'
    assert calls == [url, url]
    assert json.loads(path.read_text())[url]["leases"] == []
    assert len(audit) == 2



def test_real_json_repair_uses_parent_nonempty_admission_scope(monkeypatch, tmp_path):
    """Actual repair helper and nested pipeline share the parent's lease file."""
    from czjLLM.infrastructure import ollama_lb

    monkeypatch.chdir(tmp_path)
    scope = tmp_path / "job"
    scope.mkdir()
    url = "http://private-model.invalid"
    worker = pc.PromptAPIPipeline(
        task="to json", content="synthetic input", promptFile="",
        model_spec={"model_name": "test-model", "base_url": [url],
                    "max_concurrent_per_endpoint": 1},
        PGMSubDir=str(scope), audit_run_id="repair-scope",
        audit_path=str(scope / "audit.csv"),
    )
    monkeypatch.setattr(worker, "extract_MainFileName_and_input_text",
                        lambda: ("", "", ""))
    monkeypatch.setattr(pc, "generate_prompt", lambda **kwargs: "repair")
    monkeypatch.setattr(pc, "log_llm_call", lambda **kwargs: None)
    calls = []
    path = scope / "logs" / "base_url_load.json"

    def select_now(*args, **kwargs):
        return ollama_lb.select_idle_ollama_url(
            *args, **kwargs, admission_timeout_sec=0,
        )

    def provider(*args, **kwargs):
        assert len(json.loads(path.read_text())[url]["leases"]) == 1
        assert not (tmp_path / "logs" / "base_url_load.json").exists()
        if calls:
            with pytest.raises(ollama_lb.EndpointCapacityUnavailable):
                select_now([url], PGMSubDir=str(scope), return_lease_token=True,
                           max_concurrent_per_endpoint=1)
        calls.append(1)
        return _response('[{"a":1,}]' if len(calls) == 1 else '[{"a":1}]'), 0.0

    monkeypatch.setattr(pc, "select_idle_ollama_url", select_now)
    monkeypatch.setattr(pc, "CallLLMAPI", provider)
    result = worker.proc()
    assert result["ok"]
    assert json.loads(result["output"]) == [{"a": 1}]
    assert len(calls) == 2
    assert json.loads(path.read_text())[url]["leases"] == []


@pytest.mark.parametrize("capped", [True, False])
def test_both_worker_paths_choose_live_call_lease_for_explicit_cap(capped):
    import ast
    import inspect
    import textwrap
    for method in (pc.PromptAPIPipeline.proc, pc.PromptAPIPipeline.proc_0112):
        tree = ast.parse(textwrap.dedent(inspect.getsource(method)))
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and ast.unparse(node.func) == "maintain_url_load_lease"]
        assert len(calls) == 1
        spread = [kw.value for kw in calls[0].keywords if kw.arg is None]
        assert len(spread) == 1
        node = spread[0]
        assert isinstance(node, ast.IfExp)
        assert ast.unparse(node.test) == "endpoint_cap is not None"
        assert ast.literal_eval(node.body if capped else node.orelse) == (
            {"max_elapsed_seconds": None} if capped else {}
        )
