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
