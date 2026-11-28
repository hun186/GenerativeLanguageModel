"""Strict single-choice OpenAI-compatible text stream assembly.

Only completed streams with actual provider usage enter the existing
non-streaming response validation path. No partial response is returned.
"""
from __future__ import annotations

import time
from openai.types.chat import ChatCompletion

MAX_STREAM_TEXT_BYTES = 16 * 1024 * 1024
MAX_STREAM_CHUNKS = 65536


class IncompleteTextStream(ValueError):
    """Fixed diagnostic only; never embed provider output or request text."""


def _count(value):
    return type(value) is int and 0 <= value <= 2**63 - 1


def collect_text_completion(stream, *, started_at, activity=None):
    content = []
    text_bytes = 0
    chunks = 0
    first = first_thinking = first_content = None
    finish = None
    usage = None
    identity = None
    with stream:
        for chunk in stream:
            chunks += 1
            if chunks > MAX_STREAM_CHUNKS:
                raise IncompleteTextStream("stream chunk budget exceeded")
            current_identity = (getattr(chunk, "id", None), getattr(chunk, "model", None),
                                getattr(chunk, "created", None))
            if (not isinstance(current_identity[0], str) or not current_identity[0]
                    or not isinstance(current_identity[1], str) or not current_identity[1]
                    or not _count(current_identity[2])):
                raise IncompleteTextStream("invalid stream identity")
            if identity is None:
                identity = current_identity
            elif identity != current_identity:
                raise IncompleteTextStream("inconsistent stream identity")
            choices = getattr(chunk, "choices", None)
            if not isinstance(choices, list) or len(choices) > 1:
                raise IncompleteTextStream("unsupported stream choices")
            reported = getattr(chunk, "usage", None)
            if reported is not None:
                if usage is not None:
                    raise IncompleteTextStream("duplicate stream usage frame")
                if not all(_count(getattr(reported, key, None)) for key in
                           ("prompt_tokens", "completion_tokens", "total_tokens")):
                    raise IncompleteTextStream("invalid stream usage")
                if not choices:
                    if finish is None:
                        raise IncompleteTextStream("usage before stream finish")
                    usage = reported
                    if activity is not None:
                        activity.received()
                    continue
            if not choices:
                if activity is not None:
                    activity.received()
                continue
            if finish is not None or usage is not None:
                raise IncompleteTextStream("choice after stream finish")
            choice = choices[0]
            if type(getattr(choice, "index", None)) is not int or choice.index != 0:
                raise IncompleteTextStream("unsupported stream choice index")
            delta = getattr(choice, "delta", None)
            if delta is None or getattr(delta, "role", None) not in (None, "assistant"):
                raise IncompleteTextStream("invalid stream delta")
            if any(getattr(delta, key, None) is not None for key in
                   ("tool_calls", "function_call", "refusal", "audio")):
                raise IncompleteTextStream("unsupported nontext stream delta")
            answer = getattr(delta, "content", None)
            reasoning = getattr(delta, "reasoning_content", None)
            thinking = getattr(delta, "thinking", None)
            for value in (answer, reasoning, thinking):
                if value is not None and not isinstance(value, str):
                    raise IncompleteTextStream("invalid stream text")
                if value:
                    text_bytes += len(value.encode("utf-8"))
                    if text_bytes > MAX_STREAM_TEXT_BYTES:
                        raise IncompleteTextStream("stream text budget exceeded")
            elapsed = max(0.0, time.monotonic() - started_at)
            if reasoning or thinking:
                if first_thinking is None:
                    first_thinking = elapsed
                if first is None:
                    first = elapsed
            if answer:
                if first_content is None:
                    first_content = elapsed
                if first is None:
                    first = elapsed
                content.append(answer)
            if activity is not None:
                activity.received(thinking=bool(reasoning or thinking), content=bool(answer))
            reason = getattr(choice, "finish_reason", None)
            if reason is not None:
                if reason not in ("stop", "length"):
                    raise IncompleteTextStream("unsupported stream finish reason")
                finish = reason
            if reported is not None:
                if finish is None:
                    raise IncompleteTextStream("usage before stream finish")
                usage = reported
    if identity is None or finish is None or usage is None:
        raise IncompleteTextStream("missing stream finish or provider usage")
    # A length finish is deliberately not converted to stop; existing worker
    # truncation policy remains authoritative. No reasoning text is retained.
    response = ChatCompletion(
        id=identity[0], model=identity[1], created=identity[2],
        object="chat.completion",
        choices=[{"index": 0, "finish_reason": finish,
                  "message": {"role": "assistant", "content": "".join(content)}}],
        usage=usage,
    )
    response._czjllm_ttft_seconds = first
    response._czjllm_first_thinking_seconds = first_thinking
    response._czjllm_first_content_seconds = first_content
    response._czjllm_stream_chunks = chunks
    response._czjllm_stream_timing_source = "client_monotonic_completed_sse"
    return response
