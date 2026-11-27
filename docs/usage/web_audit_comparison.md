# WEB-05D1 grouped performance comparison

The verified incremental reader partitions each identified Audit row by
exact recorded model, full endpoint string, positive Context limit and
recognized source (response, ollama_api_ps, model_spec); missing or
unrecognized context stays unknown. This is not configured num_ctx or
hardware identity. Model and endpoint values never leave the reader:
HMAC aliases use a random per-generation salt, reset on file change.
Max 32 groups; additional distinct groups count as omitted, missing
model/endpoint as unidentified. Retained groups keep all their own
samples; no mixing or guessed zero. Exact shared accumulators preserve
provider cache denominators and independently count heuristic throughput.
Group summaries are only published when the whole incremental file
snapshot is caught up. No per-browser reads. The overall view remains
authoritative for all rows; grouped heuristic comparisons are scoped to
each partition, not necessarily additive across the overall heuristic.
This adds a Web comparison table; stable operator-visible mappings,
desktop comparison panel, charts, native phase metrics and physical
large-run performance remain separate work. Project context updates
are required before ready/merge after the stacked parent contracts land.
