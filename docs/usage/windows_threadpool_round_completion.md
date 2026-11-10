# Windows LLM ThreadPool batch completion observations

Windows `round_runner.run_round` uses ThreadPoolExecutor for parallel
LLM I/O. Previously a slow first submitted Future could obscure the
fact that later Futures already completed.

The revised collector uses `FIRST_COMPLETED` observations and an index
map. Progress field `CONSUMER_STATE["thread_round_completed_count"]`
updates when any Future finishes; successful `run_round` return remains
in original input order. The timeout exception's `finished` is a
snapshot of completed Futures at the deadline, **not** a count of durable
SQL/ES ACK, persisted Success or authenticated provider responses.

At deadline, only never-started Futures can be cancelled. Running HTTP
Threads cannot safely be killed: the executor waits for them to return
before `BatchRunTimeout` escapes. During this wait,
`CONSUMER_STATE["thread_round_drain_active"]` is true and fixed aggregate
counts `thread_round_timeout_running` and
`thread_round_cancelled_before_start` describe the snapshot. These
process-local observations are not a GPU or Queue authority.
Worker-thrown TimeoutError is not mistaken for a batch deadline.

This does **not** refill idle GPUs across batch rounds, change the
number of Workers, alter provider timeouts or retry policy, change
Queue/Success ownership or trigger automatic replay. A hung HTTP call
can still leave draining blocked. The deadline detects budget expiry
but does not guarantee immediate cancellation or return.

Deterministic regression tests in
`tests/prompt_pipeline/test_round_runner_smoke.py` run in Hosted Linux
and Hosted Windows Python 3.10/3.11. Actual GPU/Windows physical
acceptance remains operator-deferred Issue #266.
