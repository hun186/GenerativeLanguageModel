# Opt-in complete OpenAI-compatible streaming response

For a provider proven to support streamed chat completions with usage, set:

```python
"llm_stream_response": True,
"llm_max_retries": 0,
```

Default is False, and the existing non-streaming API request is unchanged. This is independent of the native Ollama diagnostic. The client requests `stream=True` and `stream_options={"include_usage": True}`. Only single-choice text responses with consistent stream identity, stop/length finish and provider usage are assembled into the existing ChatCompletion result. The SDK iterator may not expose the raw SSE [DONE] marker; completion is determined by finish, usage and normal iterator exhaustion, not a claim of inspecting that marker. Separate reasoning text is discarded; the exact concatenated answer is passed to the existing JSON validation/length handling. Unsupported tool/function/refusal/audio responses, missing usage or finish, malformed or excessive chunks and interrupted streams fail without returning partial text. The 16 MiB cumulative text and 65,536 chunk budgets bound the collector, not all SDK/network buffering. No automatic fallback to non-streaming; explicit zero SDK retries does not disable outer application recovery. HTTP read inactivity and scheduler round deadline retain their current meanings. Timing log on successful assembly shows first nonempty text/thinking/content chunk, not exact GPU token time; absent channels show unknown. No live progress GUI, persisted timing metrics, provider cancellation or physical endpoint verification yet. Do not activate in bulk until small-sample UAT confirms provider compatibility.
