import json
import httpx
import pytest

from czjLLM.cli_tools.ollama_native_performance_probe import (
    native_metrics, native_chat_url, probe, main,
)


def _payload(**changes):
    return dict(done=True, done_reason="stop", total_duration=4_000_000_000,
                load_duration=500_000_000, prompt_eval_count=1000,
                prompt_eval_cached_count=800, prompt_eval_duration=1_000_000_000,
                eval_count=20, eval_duration=2_000_000_000, **changes)


def test_measured_phase_rates_and_cache():
    m = native_metrics(_payload())
    assert m["cache_hit_pct"] == 80
    assert m["uncached_prefill_tok_s"] == 200
    assert m["decode_tok_s"] == 10
    assert m["model_load_s"] == 0.5


@pytest.mark.parametrize("cached", [None, -1, 1001, True, "800"])
def test_missing_or_invalid_cache_is_unknown(cached):
    p = _payload()
    p["prompt_eval_cached_count"] = cached
    m = native_metrics(p)
    assert m["cached_prompt_tokens"] is None
    assert m["cache_hit_pct"] is None
    assert m["uncached_prefill_tok_s"] is None
    assert m["decode_tok_s"] == 10


def test_zero_cache_and_zero_duration():
    p = _payload()
    p.update(prompt_eval_cached_count=0, prompt_eval_duration=0)
    m = native_metrics(p)
    assert m["cache_hit_pct"] == 0 and m["uncached_prompt_tokens"] == 1000
    assert m["uncached_prefill_tok_s"] is None
    with pytest.raises(ValueError):
        native_metrics({"done": False})


def test_repeat_identical_serial_calls_no_raw_output_or_model_in_report():
    sent = []
    def handler(request):
        assert request.url.path == "/api/chat"
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=dict(_payload(), message={"content": "private result"}))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe(client, "http://private.invalid/v1", "private-model",
                       "private input", repeats=2, think="low", num_ctx=65536)
    assert len(sent) == 2 and sent[0] == sent[1]
    assert sent[0]["stream"] is False and sent[0]["think"] == "low"
    assert sent[0]["options"]["num_ctx"] == 65536
    assert result["first_sample_cold"] == "unknown" and result["ttft_s"] is None
    assert "private" not in json.dumps(result)


def test_timeout_stops_without_replaying():
    calls = []
    def handler(request):
        calls.append(1)
        raise httpx.ReadTimeout("private request", request=request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe(client, "http://private.invalid", "model", "input", repeats=5)
    assert len(calls) == 1
    assert result["samples"][0]["status"] == "timeout"
    assert "private" not in json.dumps(result)


@pytest.mark.parametrize("url", ["ftp://host", "http://host/other",
                                 "http://user@host", "http://host?token=x"])
def test_bad_endpoint_refused(url):
    with pytest.raises(ValueError):
        native_chat_url(url)


def test_cli_requires_idle_confirmation():
    with pytest.raises(SystemExit) as exc:
        main(["--endpoint", "http://private.invalid", "--model", "model"])
    assert exc.value.code == 2


def test_stream_observes_thinking_and_answer_separately_without_retaining_text(monkeypatch):
    from types import SimpleNamespace
    from czjLLM.cli_tools import ollama_native_performance_probe as mod
    clock = [10.0]
    monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    def line(payload):
        return (json.dumps(payload) + "\n").encode()

    class Chunks(httpx.SyncByteStream):
        def __iter__(self):
            clock[0] = 11.0
            yield line({"done": False, "message": {"content": ""}})
            clock[0] = 12.0
            raw = line({"done": False, "message": {"thinking": "private thought"}})
            yield raw[:10]
            clock[0] = 13.0
            yield raw[10:]
            clock[0] = 15.0
            yield line({"done": False, "message": {"content": "private answer"}})
            clock[0] = 17.0
            yield line(_payload())
    def handler(request):
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, stream=Chunks())
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        report = probe(client, "http://private.invalid/v1", "model", "private prompt",
                       repeats=1, stream=True)
    sample = report["samples"][0]
    assert sample["status"] == "ok"
    assert sample["ttft_s"] == sample["first_thinking_chunk_s"] == 3.0
    assert sample["first_content_chunk_s"] == 5.0
    assert sample["client_elapsed_s"] == 7.0
    assert sample["cache_hit_pct"] == 80
    assert "private" not in json.dumps(report)
    assert report["ttft_basis"] == "client_first_nonempty_thinking_or_content_chunk_per_sample"


@pytest.mark.parametrize("failure", ["timeout", "truncated", "error", "bad_shape", "oversized"])
def test_stream_failure_preserves_observed_timing_but_never_replays(monkeypatch, failure):
    from czjLLM.cli_tools import ollama_native_performance_probe as mod
    calls = []
    class Chunks(httpx.SyncByteStream):
        def __iter__(self):
            yield b'{"done":false,"message":{"content":"private partial"}}\n'
            if failure == "timeout":
                raise httpx.ReadTimeout("private error")
            if failure == "error":
                yield b'{"error":"private provider error"}\n'
            elif failure == "bad_shape":
                yield b'{"done":"false","message":{}}\n'
            elif failure == "oversized":
                yield b"x" * 129
    if failure == "oversized":
        monkeypatch.setattr(mod, "MAX_STREAM_LINE_BYTES", 128)
    def handler(request):
        calls.append(1)
        return httpx.Response(200, stream=Chunks())
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        report = probe(client, "http://private.invalid", "model", "prompt",
                       repeats=5, stream=True)
    assert len(calls) == 1
    sample = report["samples"][0]
    assert sample["status"] == ("timeout" if failure == "timeout" else "invalid_or_incomplete_response")
    assert sample["first_content_chunk_s"] is not None
    assert sample["first_thinking_chunk_s"] is None
    assert "generated_tokens" not in sample
    assert "private" not in json.dumps(report)


def test_stream_requires_actual_text_for_ttft():
    def handler(request):
        return httpx.Response(200, content=json.dumps(_payload()).encode())
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        sample = probe(client, "http://private.invalid", "model", "prompt",
                       repeats=1, stream=True)["samples"][0]
    assert sample["status"] == "ok"
    assert sample["ttft_s"] is None
    assert sample["first_thinking_chunk_s"] is None
    assert sample["first_content_chunk_s"] is None
