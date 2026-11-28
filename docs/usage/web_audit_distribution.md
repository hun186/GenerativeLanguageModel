# Shared Audit distribution (WEB-05A)

The Windows GUI imports its existing distribution calculations from
audit_distribution.py. The Web service uses the same calculations through
a strict, bounded snapshot adapter. The local Web API exposes numeric
summary metrics only: samples, P50/P95/max, cache coverage and provider
hit percentage, and separate provider/heuristic throughput sample counts.

For the Web adapter, missing, changed, truncated, invalid or oversized
CSV is unavailable rather than a successful partial total. Limits:
8 MiB / 20,000 rows; no silent sampling. Existing Windows loader behavior
is retained for compatibility. Background reading is shared across browser
clients; large run incremental aggregation is subsequent work.

Audit schema currently lacks persisted TTFT/prefill/decode fields; the Web
view explicitly reports these as unavailable. A separate writer/schema
contract is needed before actual phase statistics and Context/model
comparisons. No new provider request or model setting is introduced.
