# Model-specific worker and endpoint admission settings

Optional model profile fields (existing model config modules / private profiles):

```python
64: {
    "workers_per_endpoint": 1,
    "max_concurrent_per_endpoint": 1,
},
```

The fixed positive `n_process` / `nProcess` setting still takes precedence.
Otherwise `workers_per_endpoint` multiplies the number of distinct available
local API endpoints (after the existing model probe). Without it the existing
automatic policy is unchanged. Both new fields accept positive integers only.

| Available endpoints | workers_per_endpoint=1 | workers_per_endpoint=2 |
|---|---:|---:|
| 1 | 1 | 2 |
| 2 | 2 | 4 |
| 4 | 4 | 8 |

The optional `max_concurrent_per_endpoint` constrains tracked GLM leases in
the shared `base_url_load.json` under its existing lock. Both legacy and
current PromptAPIPipeline paths pass the cap. Exploration never selects full
endpoints, and lock contention does not fall back to untracked dispatch when
the cap is configured. Admission waits up to approximately 120 seconds
(plus lock acquisition overhead) before reporting
`ENDPOINT_CAPACITY_UNAVAILABLE`, without starting an LLM HTTP request.
This is independent of the HTTP timeout. Set the worker multiplier and cap to
the same value for a one-request-per-slot policy.

Scope: this is a client-side lease admission limit, not a provider-side
concurrency guarantee. It assumes cooperating GLM workers sharing a load
file and configured with the cap; other jobs without a cap, other clients,
other load files, expired leases and requests surviving transport timeout
can still create server-side work. It does not change Ollama NUM_PARALLEL,
num_batch, or implement an endpoint circuit breaker. No production profile
or existing defaults are changed. GPU utilization and throughput require
separate real-world validation.
