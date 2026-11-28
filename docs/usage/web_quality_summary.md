# WEB-06A run quality summary

Local HTTP monitor consumes the existing producer-owned QUALITY_PATH IPC
locator and reads the canonical quality JSONL/rotation ledger using
QualityRunTailReader on a separate background thread. No browser-provided
paths, raw JSON, repair pairs, event IDs, document IDs or exception text.
2s poll, 8s freshness, 64 MiB source metadata pre/post bound, 64 segments,
existing 50k event/4M identity-character/64 KiB line limits.
Only fully observed status publishes counters: corrupt, partial, unsealed,
unsafe, over-budget, stale and dropped IPC suppress prior totals. This is
a trusted local cooperating-writer monitor, not a hostile filesystem
sandbox or hard RSS/time limit. Explicit sink acknowledgements do not prove
readback. Validation, repair, document and run incident denominators stay
separate; zero denominator remains unknown. Source contracts and real HTTP
tests added; no live GPU/ES/SQL or raw repair capture. Integration waits for
parent stack and project memory/API synchronization before ready.
