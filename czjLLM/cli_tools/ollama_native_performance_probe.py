"""Explicit serial native Ollama performance probe; no GLM sink or queue writes."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import time
from urllib.parse import urlsplit, urlunsplit

import httpx

MAX_PROMPT_BYTES = 1024 * 1024
DEFAULT_PROMPT = "Summarize the following fictional example in one sentence: A researcher measured three temperatures."


def _nonnegative_int(value):
    return value if type(value) is int and 0 <= value <= 2**63 - 1 else None


def _seconds(ns):
    value = _nonnegative_int(ns)
    return None if value is None else value / 1e9


def _rate(count, seconds):
    return count / seconds if count is not None and seconds is not None and seconds > 0 else None


def native_metrics(payload):
    """Use provider measurements only. Missing cache data is not a zero hit."""
    if not isinstance(payload, dict) or payload.get("done") is not True:
        raise ValueError("incomplete native response")
    prompt = _nonnegative_int(payload.get("prompt_eval_count"))
    cached = _nonnegative_int(payload.get("prompt_eval_cached_count"))
    if prompt is None or cached is None or cached > prompt:
        cached = None
    uncached = prompt - cached if cached is not None else None
    output = _nonnegative_int(payload.get("eval_count"))
    prefill = _seconds(payload.get("prompt_eval_duration"))
    decode = _seconds(payload.get("eval_duration"))
    reason = payload.get("done_reason")
    return {
        "provider_total_s": _seconds(payload.get("total_duration")),
        "model_load_s": _seconds(payload.get("load_duration")),
        "prompt_tokens": prompt,
        "cached_prompt_tokens": cached,
        "uncached_prompt_tokens": uncached,
        "cache_hit_pct": 100 * cached / prompt if cached is not None and prompt else None,
        "prefill_s": prefill,
        "uncached_prefill_tok_s": _rate(uncached, prefill),
        "generated_tokens": output,
        "decode_s": decode,
        "decode_tok_s": _rate(output, decode),
        "done_reason": reason if type(reason) is str and reason in ("stop", "length") else None,
    }


def native_chat_url(endpoint):
    parts = urlsplit(endpoint)
    if (parts.scheme not in ("http", "https") or not parts.hostname
            or parts.username is not None or parts.password is not None
            or parts.query or parts.fragment
            or parts.path.rstrip("/") not in ("", "/v1", "/api/chat")):
        raise ValueError("expected an HTTP(S) Ollama root, /v1 or /api/chat URL without credentials")
    return urlunsplit((parts.scheme, parts.netloc, "/api/chat", "", ""))


def probe(client, endpoint, model, prompt, *, repeats=2, num_predict=128, num_ctx=None, think=None):
    """Run identical sequential requests; first request is not guaranteed cold.

    Stop on any failed/incomplete response: a timed-out server might still
    be computing. Never retry automatically or return response text.
    """
    url = native_chat_url(endpoint)
    if type(repeats) is not int or not 1 <= repeats <= 10:
        raise ValueError("repeats must be 1..10")
    if type(num_predict) is not int or not 1 <= num_predict <= 8192:
        raise ValueError("num_predict must be 1..8192")
    if num_ctx is not None and (type(num_ctx) is not int or not 1 <= num_ctx <= 262144):
        raise ValueError("num_ctx must be 1..262144")
    if not isinstance(model, str) or not model.strip() or len(model) > 256:
        raise ValueError("invalid model")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
        raise ValueError("invalid or oversized prompt")
    if think is not None and type(think) is not bool and (
            type(think) is not str or think not in ("low", "medium", "high")):
        raise ValueError("invalid think option")
    options = {"num_predict": num_predict, "temperature": 0}
    if num_ctx is not None:
        options["num_ctx"] = num_ctx
    body = {"model": model, "messages": [{"role": "system", "content": "You are a helpful assistant"},
                                        {"role": "user", "content": prompt}],
            "stream": False, "options": options}
    if think is not None:
        body["think"] = think
    samples = []
    for index in range(1, repeats + 1):
        start = time.monotonic()
        status = "ok"
        metrics = {}
        try:
            response = client.post(url, json=body)
            response.raise_for_status()
            metrics = native_metrics(response.json())
        except httpx.TimeoutException:
            status = "timeout"
        except httpx.HTTPStatusError:
            status = "http_error"
        except httpx.RequestError:
            status = "transport_error"
        except (ValueError, TypeError):
            status = "invalid_or_incomplete_response"
        samples.append({"sample": index, "status": status,
                        "client_elapsed_s": time.monotonic() - start, **metrics})
        if status != "ok":
            break
    return {"probe_version": 1, "mode": "native_ollama_serial",
            "requested_samples": repeats, "samples": samples,
            "first_sample_cold": "unknown", "ttft_s": None}


def _read_prompt(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_PROMPT_BYTES + 1)
    if len(raw) > MAX_PROMPT_BYTES:
        raise ValueError("oversized prompt file")
    return raw.decode("utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--prompt-file")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--num-predict", type=int, default=128)
    parser.add_argument("--num-ctx", type=int)
    parser.add_argument("--think", choices=["true", "false", "low", "medium", "high"])
    parser.add_argument("--read-timeout", type=float, default=900)
    parser.add_argument("--confirm-idle", action="store_true",
                        help="Confirm the target is reserved for this serial probe; it does not use GLM leases.")
    args = parser.parse_args(argv)
    if not args.confirm_idle:
        parser.error("confirm the endpoint is idle/reserved with --confirm-idle")
    if not math.isfinite(args.read_timeout) or not 1 <= args.read_timeout <= 7200:
        parser.error("read timeout must be 1..7200 seconds")
    try:
        prompt = _read_prompt(args.prompt_file) if args.prompt_file else DEFAULT_PROMPT
        think = {"true": True, "false": False}.get(args.think, args.think)
        with httpx.Client(timeout=httpx.Timeout(connect=10, read=args.read_timeout, write=240, pool=120),
                          trust_env=False, follow_redirects=False) as client:
            result = probe(client, args.endpoint, args.model, prompt, repeats=args.repeats,
                           num_predict=args.num_predict, num_ctx=args.num_ctx, think=think)
    except (OSError, ValueError, TypeError):
        print(json.dumps({"probe_version": 1, "status": "invalid_configuration"}))
        return 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if all(s["status"] == "ok" for s in result["samples"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
