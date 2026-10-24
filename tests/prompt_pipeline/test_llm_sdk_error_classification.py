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
        (APIResponseValidationError("secret data", response=httpx.Response(200, request=request), body=None),
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
