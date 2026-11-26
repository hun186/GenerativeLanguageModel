"""Typed OpenAI-compatible request error codes: no exception-text parsing."""
import httpx
import pytest
from openai import (
    APIConnectionError, APITimeoutError, APIResponseValidationError,
    APIStatusError, RateLimitError,
)

from czjLLM.prompt_pipeline import llm_caller


def _request():
    return httpx.Request("POST", "https://model-private.invalid/v1/chat/completions")


def _http_error(status):
    response = httpx.Response(status, request=_request())
    return APIStatusError("secret response details", response=response, body=None)


def test_sdk_error_types_have_fixed_privacy_safe_categories():
    request = _request()
    samples = (
        (APITimeoutError(request=request), "WORKER_LLM_TIMEOUT_EXCEPTION"),
        (APIConnectionError(request=request), "WORKER_LLM_CONNECTION_EXCEPTION"),
        (RateLimitError("private account", response=httpx.Response(429, request=request), body=None),
         "WORKER_LLM_RATE_LIMIT_EXCEPTION"),
        (_http_error(502), "WORKER_LLM_HTTP_SERVER_EXCEPTION"),
        (_http_error(503), "WORKER_LLM_HTTP_SERVER_EXCEPTION"),
        (_http_error(401), "WORKER_LLM_HTTP_CLIENT_EXCEPTION"),
        (_http_error(400), "WORKER_LLM_HTTP_CLIENT_EXCEPTION"),
        (APIResponseValidationError(response=httpx.Response(200, request=request), body=None, message="secret data"),
         "WORKER_LLM_RESPONSE_VALIDATION_EXCEPTION"),
    )
    for error, expected in samples:
        code = llm_caller.classify_llm_call_exception(error)
        assert code == expected
        assert "secret" not in code.lower()
        assert "private" not in code.lower()
    assert llm_caller.classify_llm_call_exception(_http_error(302)) == "WORKER_LLM_CALL_EXCEPTION"


def test_legacy_runtime_wrapper_uses_typed_direct_cause_only():
    request = _request()
    for sdk_error, expected in (
        (APITimeoutError(request=request), "WORKER_LLM_TIMEOUT_EXCEPTION"),
        (APIConnectionError(request=request), "WORKER_LLM_CONNECTION_EXCEPTION"),
    ):
        try:
            raise RuntimeError("private legacy error: do not parse this") from sdk_error
        except RuntimeError as caught:
            assert llm_caller.classify_llm_call_exception(caught) == expected
    # Message bait is untrusted. No source can be derived from text alone.
    for error in (
        RuntimeError("LLM_CALL_TIMEOUT_OR_CONN: timeout"),
        ConnectionError("APITimeoutError / 429 / server returned 503"),
        ValueError("RateLimitError 429"),
        RuntimeError("unknown private content"),
    ):
        assert llm_caller.classify_llm_call_exception(error) == "WORKER_LLM_CALL_EXCEPTION"


def test_actual_call_llm_api_preserves_typed_cause_from_mock_transport(monkeypatch):
    # The actual OpenAI SDK call with an isolated in-memory transport proves
    # the historical RuntimeError wrapper retains the classifier's SDK cause.
    monkeypatch.setattr(llm_caller, "finalize_llm_user_content",
                        lambda content, **_kwargs: content)
    count = [0]

    def timeout_transport(request):
        count[0] += 1
        raise httpx.ReadTimeout("private timeout detail", request=request)

    with httpx.Client(transport=httpx.MockTransport(timeout_transport)) as client:
        with pytest.raises(RuntimeError) as caught:
            llm_caller.CallLLMAPI(
                "private prompt text",
                model_spec={"api_key": "private", "model_name": "test",
                            "base_url": "https://model-private.invalid/v1"},
                http_client=client,
            )
    assert count[0] >= 1
    assert isinstance(caught.value.__cause__, APITimeoutError)
    assert llm_caller.classify_llm_call_exception(caught.value) == "WORKER_LLM_TIMEOUT_EXCEPTION"



def test_model_request_policy_on_actual_sdk_transport(monkeypatch):
    import json

    monkeypatch.setattr(llm_caller, "finalize_llm_user_content",
                        lambda content, **kwargs: content)
    seen = []

    def transport(request):
        seen.append((json.loads(request.content), request.extensions["timeout"]))
        raise httpx.ReadTimeout("test", request=request)

    with httpx.Client(transport=httpx.MockTransport(transport),
                      timeout=httpx.Timeout(10.0, read=240.0)) as client:
        with pytest.raises(RuntimeError):
            llm_caller.CallLLMAPI(
                "synthetic prompt",
                model_spec={"api_key": "test", "model_name": "test",
                            "base_url": "https://model.invalid/v1",
                            "llm_read_timeout_sec": 900,
                            "llm_max_retries": 0, "thinking_level": False},
                http_client=client,
            )
    assert len(seen) == 1
    body, timeout = seen[0]
    assert body["reasoning_effort"] == "none"
    assert timeout["read"] == 900
    assert timeout["connect"] == 10


@pytest.mark.parametrize("key,value", [
    ("llm_read_timeout_sec", True), ("llm_read_timeout_sec", float("inf")),
    ("llm_round_timeout_sec", 0), ("llm_max_retries", -1),
    ("llm_max_retries", False), ("thinking_level", "unsupported"),
])
def test_invalid_model_request_policy_rejected(key, value):
    from czjLLM.prompt_pipeline.request_policy import request_policy
    with pytest.raises(ValueError, match=key):
        request_policy({key: value})


def test_request_policy_absent_keeps_legacy_defaults():
    from czjLLM.prompt_pipeline.request_policy import request_policy
    assert request_policy({}) == (None, None, None)
    assert request_policy({"thinking_level": "low"}) == (None, None, "low")


def test_explicit_thinking_replaces_automatic_suffix():
    from czjLLM.prompt_pipeline.prompt_generator import finalize_llm_user_content
    spec = {"model_name": "qwen3:8b", "thinking_level": "high"}
    assert finalize_llm_user_content("synthetic", model_spec=spec) == "synthetic"
    assert finalize_llm_user_content(
        "synthetic", model_spec=dict(spec, no_think_suffix="/no_think"),
    ).endswith("/no_think")


def test_extract_resume_fingerprint_tracks_effective_reasoning_policy_only():
    from types import SimpleNamespace
    from czjLLM.prompt_pipeline.pipeline_controller import _extract_stage_provenance_fingerprint
    ctx = SimpleNamespace(taskSetting={}, task="extract", think_mode=True,
                          model_spec={"model_name": "qwen3:8b"})
    def fingerprint(**settings):
        ctx.model_spec = {"model_name": "qwen3:8b", **settings}
        return _extract_stage_provenance_fingerprint("synthetic extract", ctx)
    baseline = fingerprint()
    assert fingerprint(**{"api_key": bytes([1, 2, 3]).hex(), "llm_read_timeout_sec": 900}) == baseline
    low = fingerprint(thinking_level="low")
    assert low != baseline and low != fingerprint(thinking_level="high")
    assert low == fingerprint(thinking_level="low", **{"api_key": bytes([4, 5, 6]).hex()})
    assert low != fingerprint(thinking_level="low", no_think_suffix=None)
    assert low != fingerprint(thinking_level="low", no_think_suffix="/no_think")
    assert fingerprint(thinking_level=False) == fingerprint(thinking_level="none")
    with pytest.raises(ValueError, match="thinking_level"):
        fingerprint(thinking_level="invalid")


def test_legacy_prompt_generation_does_not_preappend_automatic_suffix_for_explicit_effort():
    from types import SimpleNamespace
    from czjLLM.prompt_pipeline.prompt_generator import PromptGenerator, finalize_llm_user_content
    ctx = SimpleNamespace(task="raw synthetic instruction", think_mode=False,
                          model_spec_name="qwen3:8b", model_spec={"model_name": "qwen3:8b"})
    legacy = PromptGenerator(ctx).build("source")
    assert legacy.endswith("/no_think")
    ctx.model_spec["thinking_level"] = "low"
    prompt = PromptGenerator(ctx).build("source")
    assert not prompt.endswith("/no_think")
    assert finalize_llm_user_content(prompt, model_spec=ctx.model_spec) == prompt
    ctx.model_spec["no_think_suffix"] = "/no_think"
    assert PromptGenerator(ctx).build("source").endswith("/no_think")


def test_reduction_runtime_fingerprints_bind_opt_in_reasoning_and_suffix(tmp_path):
    from types import SimpleNamespace
    from czjLLM.reduction.runtime_task import ProductionTaskRuntime
    from czjLLM.reduction.runtime_text import TextRoundRuntimeAdapter

    def metadata(**settings):
        ctx = SimpleNamespace(task="synthetic", taskSetting={}, think_mode=False,
                              model_spec_name="test-model", max_tokens=4096,
                              model_spec={"model_name": "qwen3:8b", **settings})
        task = ProductionTaskRuntime(ctx)
        text = TextRoundRuntimeAdapter(ctx=ctx, item_workspace=tmp_path,
                                       round_task="synthetic")
        return task.fingerprint_metadata(), text.fingerprint_metadata(), text.execution_fingerprint()

    baseline = metadata()
    assert metadata(llm_read_timeout_sec=900, llm_round_timeout_sec=1200,
                    llm_max_retries=0, **{"api_key": bytes([1, 2, 3]).hex()}) == baseline
    low = metadata(thinking_level="low")
    high = metadata(thinking_level="high")
    explicit_auto = metadata(thinking_level="low", no_think_suffix=None)
    explicit_force = metadata(thinking_level="low", no_think_suffix="/no_think")
    for index in range(3):
        assert low[index] != baseline[index] and low[index] != high[index]
        assert low[index] != explicit_auto[index] and low[index] != explicit_force[index]
    assert metadata(thinking_level="low", no_think_suffix="") == low
    assert metadata(thinking_level=False) == metadata(thinking_level="none")
    assert metadata(thinking_level="low", **{"api_key": bytes([4, 5, 6]).hex()}) == low
    with pytest.raises(ValueError, match="thinking_level"):
        metadata(thinking_level="unsupported")


def test_effective_model_startup_policy_reports_real_context_and_explicit_controls():
    from types import SimpleNamespace
    from czjLLM.prompt_pipeline.effective_model_policy import (
        effective_model_startup_policy, format_effective_model_startup_policy,
    )
    spec = {
        "base_url": ["http://private-a.invalid/v1", "http://private-b.invalid/v1"],
        "workers_per_endpoint": 1, "max_concurrent_per_endpoint": 1,
        "llm_read_timeout_sec": 900, "llm_round_timeout_sec": 1200,
        "llm_max_retries": 0, "thinking_level": "low",
        "api_key": bytes([1, 2, 3, 4]).hex(),
    }
    ctx = SimpleNamespace(model_spec=spec, n_process=2)
    assert effective_model_startup_policy(ctx) == {
        "available_endpoint_count": 2, "configured_worker_budget": 2,
        "context_worker_budget": 2, "worker_budget_matches_profile": True,
        "endpoint_lease_limit": 1, "http_read_inactivity_seconds": 900.0,
        "round_deadline_seconds": 1200.0, "sdk_retry_count": 0,
        "reasoning_effort": "low", "reasoning_suffix_policy": "disabled",
    }
    line = format_effective_model_startup_policy(ctx)
    assert "SDK_retries=0" in line and "provider_support=unverified" in line
    assert "private-a" not in line and spec["api_key"] not in line
    ctx.n_process = 4
    assert "worker_budget_match=NO" in format_effective_model_startup_policy(ctx)
    spec["n_process"] = 4
    assert effective_model_startup_policy(ctx)["worker_budget_matches_profile"] is True
    ctx.llm_round_timeout_sec = 300
    assert effective_model_startup_policy(ctx)["round_deadline_seconds"] == 300
    assert spec["llm_round_timeout_sec"] == 1200


def test_effective_startup_policy_absent_and_invalid_are_not_guessed(monkeypatch):
    from types import SimpleNamespace
    from czjLLM.prompt_pipeline.effective_model_policy import format_effective_model_startup_policy
    monkeypatch.setenv("CZJLLM_LLM_ROUND_TIMEOUT_SEC", "600")
    ctx = SimpleNamespace(model_spec={"base_url": "http://private.invalid"}, n_process=2)
    line = format_effective_model_startup_policy(ctx)
    for part in ("profile_workers=auto", "endpoint_lease_cap=legacy uncapped",
                 "HTTP_read_inactivity_s=client default", "SDK_retries=SDK default",
                 "round_deadline_s=600.0", "reasoning_effort=provider default"):
        assert part in line
    ctx.model_spec["thinking_level"] = "sensitive-invalid-value"
    assert format_effective_model_startup_policy(ctx) == (
        "[Effective Model Configuration] unavailable (invalid or unresolved policy)"
    )
    assert "unavailable" in format_effective_model_startup_policy(SimpleNamespace())


def test_effective_policy_is_logged_before_legacy_worker_launch():
    import inspect
    from czjLLM.sql_mode.runtime.orchestrator import run_pipeline
    source = inspect.getsource(run_pipeline)
    assert source.index("tlog(format_effective_model_startup_policy(ctx))") < source.index("start_workers(")


def _stream_sse_frame(choices, usage=None):
    import json
    return ("data: " + json.dumps({
        "id": "synthetic-stream", "model": "model", "created": 1,
        "object": "chat.completion.chunk", "choices": choices, "usage": usage,
    }) + "\n\n").encode()


@pytest.mark.parametrize("finish", ["stop", "length"])
@pytest.mark.parametrize("usage_on_finish", [True, False])
def test_actual_sdk_stream_assembles_exact_answer_and_preserves_usage(monkeypatch, finish, usage_on_finish):
    import json
    monkeypatch.setattr(llm_caller, "resolve_context_limit", lambda *a, **kw: (0, ""))
    logs = []
    monkeypatch.setattr(llm_caller, "tlog", logs.append)
    usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120,
             "prompt_tokens_details": {"cached_tokens": 80}}
    frames = [
        _stream_sse_frame([{"index": 0, "delta": {"role": "assistant"}}]),
        _stream_sse_frame([{"index": 0, "delta": {"reasoning_content": "private thought"}}]),
        _stream_sse_frame([{"index": 0, "delta": {"content": '[{"a":'}}]),
        _stream_sse_frame([{"index": 0, "delta": {"content": '1}]'}}]),
        _stream_sse_frame([{"index": 0, "delta": {}, "finish_reason": finish}],
                          usage if usage_on_finish else None),
    ]
    if not usage_on_finish:
        frames.append(_stream_sse_frame([], usage))
    frames.append(b"data: [DONE]\n\n")
    calls = []
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            yield from frames
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=Stream())
    spec = {"base_url": "http://model.invalid/v1", "model_name": "model",
            "llm_stream_response": True, "llm_max_retries": 0}
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response, _ = llm_caller.CallLLMAPI("private input", model_spec=spec, http_client=client)
    assert len(calls) == 1
    assert calls[0]["stream"] is True and calls[0]["stream_options"] == {"include_usage": True}
    assert response.choices[0].message.content == '[{"a":1}]'
    assert response.choices[0].finish_reason == finish
    assert response.usage.prompt_tokens_details.cached_tokens == 80
    assert response._czjllm_ttft_seconds is not None
    assert response._czjllm_first_thinking_seconds <= response._czjllm_first_content_seconds
    assert "private thought" not in str(response)
    assert "private" not in "\n".join(logs)


@pytest.mark.parametrize("case", ["missing_finish", "missing_usage", "duplicate_choice", "tool_call", "oversized", "timeout", "read_error", "protocol_error"])
def test_actual_sdk_stream_failure_does_not_return_partial_or_replay(monkeypatch, case):
    from czjLLM.prompt_pipeline import stream_completion as mod
    calls = []
    closed = []
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            yield _stream_sse_frame([{"index": 0, "delta": {"content": "private partial"}}])
            if case == "timeout":
                raise httpx.ReadTimeout("synthetic timeout")
            if case == "read_error":
                raise httpx.ReadError("synthetic read error")
            if case == "protocol_error":
                raise httpx.RemoteProtocolError("synthetic protocol error")
            if case == "missing_usage":
                yield _stream_sse_frame([{"index": 0, "delta": {}, "finish_reason": "stop"}])
            elif case == "duplicate_choice":
                yield _stream_sse_frame([{"index": 1, "delta": {"content": "x"}}])
            elif case == "tool_call":
                yield _stream_sse_frame([{"index": 0, "delta": {"function_call": {"name": "tool", "arguments": "{}"}}}])
            yield b"data: [DONE]\n\n"
        def close(self):
            closed.append(True)
    if case == "oversized":
        monkeypatch.setattr(mod, "MAX_STREAM_TEXT_BYTES", 4)
    def handler(request):
        calls.append(1)
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=Stream())
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        expected = RuntimeError if case in {"timeout", "read_error", "protocol_error"} else mod.IncompleteTextStream
        with pytest.raises(expected) as caught:
            llm_caller.CallLLMAPI("input", model_spec={"base_url": "http://model.invalid/v1",
                                  "llm_stream_response": True, "llm_max_retries": 0},
                                  http_client=client)
    assert calls == [1] and closed
    if case in {"timeout", "read_error", "protocol_error"}:
        expected_code = ("WORKER_LLM_TIMEOUT_EXCEPTION" if case == "timeout"
                         else "WORKER_LLM_CONNECTION_EXCEPTION")
        assert llm_caller.classify_llm_call_exception(caught.value) == expected_code
        assert isinstance(caught.value.__cause__, APITimeoutError if case == "timeout" else APIConnectionError)


def test_stream_policy_requires_explicit_opt_in_and_zero_retries():
    from czjLLM.prompt_pipeline.request_policy import stream_response_enabled
    assert stream_response_enabled({}) is False
    assert stream_response_enabled({"llm_stream_response": False}) is False
    assert stream_response_enabled({"llm_stream_response": True, "llm_max_retries": 0}) is True
    for spec in ({"llm_stream_response": True}, {"llm_stream_response": True, "llm_max_retries": 1},
                 {"llm_stream_response": True, "llm_max_retries": False}, {"llm_stream_response": "true"}):
        with pytest.raises(ValueError):
            stream_response_enabled(spec)
