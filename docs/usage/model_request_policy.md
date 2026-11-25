# Model-specific request policy (opt-in)

Set these fields in the model profile, including the private model profile
if appropriate. Existing models without these fields retain current behavior.

```python
64: {
    "llm_read_timeout_sec": 900,
    "llm_round_timeout_sec": 1200,
    "llm_max_retries": 0,
    "thinking_level": "low",
},
```

- Read timeout is per HTTP read inactivity, not a total request deadline.
  Connection, write and pool timeouts remain unchanged.
- SDK retry count: 0 prevents automatic HTTP replay during diagnostics.
  It does not disable application-level JSON repair or split/recovery logic.
- Round timeout: explicit context setting wins, then model, then legacy
  environment/default. The round deadline may cover multiple calls and
  refill workers; allow sufficient time for repair. Windows safe draining
  may wait beyond the scheduling deadline for outstanding calls.
- Thinking: explicit effort is sent in the OpenAI-compatible request body
  as reasoning_effort. False is mapped to "none"; named efforts are
  provider/model dependent. Verify actual support with the endpoint;
  unsupported efforts may be ignored or rejected. Absent configuration
  retains the current automatic Qwen suffix behavior.
- For current Ollama compatibility see
  https://docs.ollama.com/api/openai-compatibility and
  https://docs.ollama.com/capabilities/thinking.

This change does not make requests streaming, add provider cancellation or
a circuit breaker, or change the production model profiles. Verify actual
response quality, latency and token usage on a small controlled sample.
