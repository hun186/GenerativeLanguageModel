# Native Ollama serial performance probe

This opt-in diagnostic is separate from GLM's OpenAI-compatible production
requests. Reserve an idle endpoint first: the probe intentionally does not
use GLM endpoint leases, modify model settings, unload a model, write to ES,
or retry a timed-out request. Do not run it alongside a production batch.

Example (replace endpoint and model with the exact installed local values):

```bash
python -m czjLLM.cli_tools.ollama_native_performance_probe --endpoint http://127.0.0.1:11435 --model inkling-2-mini:latest --num-ctx 65536 --think low --repeats 2 --num-predict 128 --read-timeout 900 --confirm-idle
```

Optional `--prompt-file` reads a UTF-8 test prompt (max 1 MiB); use a
non-sensitive representative full user prompt to measure long-input cost.
Requests use identical messages and are serial. The first is not necessarily
cold, the second is not necessarily a cache hit. Compare provider-reported
load, prefill, decode, total and client wall time; cache percentage is reported
only if the server explicitly returns a valid cache count. Uncached prefill
rate is (prompt tokens minus cached tokens) / provider prefill seconds.
If cache count or duration is unavailable, the corresponding rate is null,
not a guessed zero. Generated token rate includes whatever the server counts
in eval_count (possibly reasoning). A length finish is not a quality pass.
Native think values are model/provider-dependent and not a guarantee that the
OpenAI-compatible reasoning_effort path behaves identically.

Non-streaming cannot measure TTFT, which stays null. The probe emits one
JSON summary to stdout, no raw prompt, response, endpoint or credentials.
It stops at the first failure, since the provider might still compute after
a timeout. This is not cancellation, a production audit schema change,
or a real GPU performance result. Run separately on each reserved endpoint
with identical controls before testing simultaneous GLM dispatch.

Reference: https://docs.ollama.com/api/chat
