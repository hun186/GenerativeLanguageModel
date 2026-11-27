# Shared stream timing distributions (WEB-05B2 consumer)

The desktop summary and local Web table use one numeric reader for the
append-only SSE suffix introduced by #388. Legacy CSV remains usable.
Coverage is all Audit calls, not the number of attempted SSE calls.
Reported, unreported and malformed timing rows are disjoint; no-text
rows are a subset of reported rows. A failed downstream operation can
still have a valid completed SSE observation. Each metric has its own
sample count, P50/P95/max, including genuine zero measurements. Missing
or invalid optional telemetry is never zero-filled and does not rewrite
the separate call outcome counters. No model, prompt, URL, or raw text
is added to the HTTP summary. TTFT is first nonempty thinking or content,
not native prefill. Native prefill/decode remain unavailable.

The existing desktop histogram layout is unchanged. Web adds a separate
timing table; charts/grouped views and incremental large-Audit aggregation
remain subsequent work. Consumer is backward-compatible before writer
lands, but end-to-end deployment requires both #388 and this PR.
