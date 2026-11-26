"""Best-effort, numeric, per-call stream activity observations.

No raw prompt, answer, reasoning, URL, model name or provider id is sent to
the observer. A chunk is evidence of client receipt, not GPU utilization.
"""
from __future__ import annotations

import time
import uuid

INTERVAL_SECONDS = 10.0


class StreamActivity:
    def __init__(self, sink, *, started_at):
        self._sink = sink
        self._started = started_at
        self._id = uuid.uuid4().hex
        self._last_emit = None
        self._last_chunk = None
        self._chunks = 0
        self._thinking_seen = False
        self._content_seen = False
        self._finished = False
        self._emit("started", started_at)

    def _emit(self, event, now):
        self._last_emit = now
        try:
            self._sink({
                "call_id": self._id,
                "event": event,
                "elapsed_s": max(0.0, now - self._started),
                "last_chunk_elapsed_s": (
                    None if self._last_chunk is None
                    else max(0.0, self._last_chunk - self._started)
                ),
                "chunks": self._chunks,
                "thinking_seen": self._thinking_seen,
                "content_seen": self._content_seen,
            })
        except Exception:
            # An observational sink must not turn a valid response into a
            # failed task. It receives no mutable model/response state.
            pass

    def received(self, *, thinking=False, content=False):
        if self._finished:
            return
        now = time.monotonic()
        self._chunks += 1
        self._last_chunk = now
        changed = (self._chunks == 1 or (thinking and not self._thinking_seen)
                   or (content and not self._content_seen))
        self._thinking_seen |= bool(thinking)
        self._content_seen |= bool(content)
        if changed or now - self._last_emit >= INTERVAL_SECONDS:
            self._emit("received", now)

    def close(self, *, completed):
        if self._finished:
            return
        self._finished = True
        self._emit("assembled" if completed else "failed", time.monotonic())


def format_stream_activity(event):
    """Fixed numeric line for the existing log path, never includes content."""
    last = event["last_chunk_elapsed_s"]
    return (
        "[LLM stream activity] "
        f"call={event['call_id']} event={event['event']} "
        f"elapsed_s={event['elapsed_s']:.2f} "
        f"last_chunk_elapsed_s={'unknown' if last is None else format(last, '.2f')} "
        f"chunks={event['chunks']} "
        f"thinking_seen={int(event['thinking_seen'])} "
        f"content_seen={int(event['content_seen'])}"
    )
