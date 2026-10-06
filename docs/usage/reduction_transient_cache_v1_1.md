# Reduction v1.1 transient semantic-call cache

This optional optimization removes duplicate **semantic LLM calls inside one
run**. It does not create a second persisted result authority.

## Configuration

The root policy is disabled by default:

```yaml
reduction_transient_cache:
  enabled: false
  max_entries: 128
  max_output_characters: 200000
  max_total_output_characters: 2000000
```

The canonical CLI projects this mapping once before TXT/Table/SQL/ES scheduling.
Unknown keys, non-boolean `enabled`, non-positive integer limits, and an
entry-size limit larger than the total-size limit fail early.

## Authority boundary

The cache is attached to the root run context and exists only in process memory.
It is not a checkpoint, manifest, aggregate, SQL/ES destination value, or
cross-run cache. Persisted SQL/ES output plus its configured processing identity
remains the cross-run reuse/freshness authority, and committed checkpoints
remain hierarchical resume authority.

Only a successful `semantic_llm` runtime result is eligible. Failed/blank
results are never cached. A cache hit reports zero new external-model cost.
Concurrent misses for the same key are coalesced with a per-key single-flight:
one caller owns the external call while later callers wait cooperatively. A
successful owner result is shared with current waiters even when it is too large
to retain in the LRU; if the owner fails, waiters are released and one may retry.

## Key and privacy contract

Lookup happens **after** normal prompt rendering and one-chunk tokenizer
preflight, so caching cannot bypass existing size validation. The key binds:

- SHA-256 of the exact rendered prompt bytes; raw prompt text is not used as a
  stored key;
- the existing allowlisted production model/generation fingerprint metadata;
- a dedicated cache-key contract version.

API keys, passwords, raw endpoint URLs, audit paths, filesystem paths,
cancellation state and observer objects are not included in the key metadata.
Cached output text necessarily remains in RAM while retained by the run-scoped
LRU, but it is never written by this cache to disk, logs, manifests or
persistent stores.

## Bounds and eviction

The cache is a thread-safe LRU bounded by both entry count and total output
characters, with per-key single-flight coordination outside those persisted
bounds. Oversized outputs are returned normally and may be shared with callers
already waiting on that flight, but are not retained for later calls. Waiting
polls the existing cooperative cancellation boundary. The safe snapshot exposes
entry/output/in-flight/waiter counts only; it contains neither keys nor payloads.

This v1.1 slice intentionally does **not** implement generic member-result
caching. Any future member cache must separately prove side-effect safety,
identity semantics, cancellation behavior, accounting, and privacy before it
can be enabled.
