# Shared completed SSE timing distributions (WEB-05B3)

Read the #388 optional source-tagged timing suffix, compatible with legacy
CSV files. The writer PR remains separate; this reader can be tested using
the same published CSV contract without changing production transport.
Windows summary and local Web table share one aggregation pass. Each metric
has its own count, P50/P95/max (Web), with real zero distinguished from
unknown. Counts are all Audit call rows, including non-slice calls and
completed responses followed by a local processing failure. Missing,
invalid and completed-with-no-text observations are separately counted.
Malformed timing is excluded from timing distributions without changing
existing call outcome statistics. Only the known completed-SSE monotonic
source is accepted. TTFT is first nonempty text, not first byte or native
prefill. Native durations remain unknown; no provider phase inferred.
The existing strict snapshot budgets remain. Incremental large-run
aggregation and authenticated per-model comparisons are separate work.
