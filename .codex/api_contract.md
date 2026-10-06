# api contract

## Current Summary

### Root reduction configuration

- Root `reduction` is opt-in and strictly accepts `enabled`, `profile`, `controller`, `options`, `controller_options`, and `runtime`. Explicit reduction is incompatible with `merge_slices=true`; absence or disabled reduction preserves legacy behavior.
- Controllers are `single_pass`, `fixed_rounds`, and `adaptive_hierarchical`. Hierarchical controllers require `profile: concat_text`, strict controller options and nonblank `runtime.round_task`.
- Canonical reducer profiles are `concat_text`, `concat_json_list`, `legacy_json_deep_merge`, `dedup`, `group`, `entity_union`, `rank`, `top_k`, `composite`, `semantic_llm`, and `structured_relational`. Detailed aliases/examples live in `docs/usage/reduction_engine_v1.md`.
- `execution_budget_capacity`, when configured, is a positive integer process-local hard ceiling for leaf work. Budget capacity is operational and excluded from semantic identity.

### Hierarchical checkpoints and execution identity

- `reduce_hierarchical_text()` consumes prepared text, deterministic controller policy and a narrow next-round callback. Completed checkpoint JSON is the commit marker; corrupt/incompatible committed chains fail closed.
- Checkpointed execution requires deterministic semantic identity. Effective task/prompt semantics, tokenizer/input-cut and model-generation semantics intentionally influence the fingerprint hash; plaintext prompts, credentials, raw endpoint URLs, paths, PIDs and other operational values are not persisted as fingerprint metadata.
- Fixed/adaptive hierarchical production execution uses the prompt-aware tokenizer/render/LLM boundary and never recursively calls business-stage/combine orchestration.

### ReductionStage and bounded nesting

- `ReductionStage` defaults to `failure_policy.mode=require_all`. `allow_partial` additionally accepts strict `min_success_count` and `min_success_ratio`; failed members never enter reducers and only `ExecutionError` is recoverable.
- `ExecutionCancelled` is never a recoverable member failure. Programmer/system faults such as `TypeError`, `AssertionError`, and `MemoryError` remain outside the partial-success channel.
- `ExecutionNestingState` hard-limits v1 to one nested ReductionStage boundary and at most four active PipelineRef names. Cycles/depth overflow fail closed.
- Nested ReductionStage executables reject semantic/composite-semantic child reducers. `TokenizerInputPreparer` and `TokenizerRoundPreparer` use production prompt-aware preflight where available.
- One checkpointed `ReductionStageExecutable` instance serializes complete child-stage executions conservatively; the lock is operational and excluded from semantic identity.

### Collection and aggregate APIs

- Python collection APIs expose immutable `LogicalWorkUnit`, `CollectionManifest`, SQL/ES collection adapters, manifest persistence, `AggregateOutput`, and idempotent aggregate sinks. There is no general collection YAML surface.
- Caller-supplied member ordering is authoritative and fingerprinted. Aggregate sinks reject conflicting lineage; existing ES documents require complete matching aggregate lineage before replacement.
- Complete `AggregateOutput` mapping preserves lineage for aggregate-of-aggregates use.

### Persisted reuse and semantic freshness

- SQL/ES persisted destination results are the v1 cross-run reuse authority; runtime workspaces are not a reusable result cache.
- Persisted semantic processing identity is opt-in. SQL uses `semantic_freshness.execution_fingerprint` plus a required nonconflicting `processing_identity_column`; ES uses `rerun.execution_fingerprint`.
- `execution_fingerprint: auto` derives identity from effective Executable semantics. Omitting the option leaves no expected identity bound and legacy completeness/rerun rules continue to govern reuse.
- Discovery and pre-dispatch/completion recheck share destination-specific freshness semantics. Recheck diagnostics are bounded and payload-free.

### Transient semantic cache (v1.1 opt-in)

- Root `reduction_transient_cache` is a separate operational policy and defaults to disabled. It accepts only `enabled`, `max_entries`, `max_output_characters`, and `max_total_output_characters`.
- Enabled caching is root-run scoped and memory-only. It caches only successful semantic LLM outputs after normal prompt rendering and tokenizer preflight; failures and oversized outputs are not retained.
- Concurrent misses for one key are per-key single-flight: one owner executes the external call, waiters poll cooperative cancellation, successful output is shared with current waiters, and owner failure releases waiters so one may retry.
- Cache keys use SHA-256 of the exact rendered prompt plus the existing allowlisted production model/generation fingerprint metadata. Raw prompts, credentials and raw endpoint URLs are not stored in key metadata.
- Cache hits incur zero new external-model cost. Persisted SQL/ES output remains cross-run reuse authority and committed checkpoints remain resume authority. Generic member-result caching is not part of this slice.

### Cancellation and observability

- Production cancellation is cooperative. It stops new scheduling and semantic continuation but does not hard-kill an already-running external request; already-running deterministic safe-drain work may complete.
- Canonical production Reduction events/counters are payload-free. Observer, tags and cancellation state are operational and excluded from semantic fingerprints.

### Retention

- Root `reduction_retention` is a separate frozen operational policy and defaults to disabled.
- Defaults: terminal checkpoint 14 days, incomplete checkpoint 30 days, transient runtime 24 hours, `cleanup_transient_on_success=true`, 100 delete entries, 1 GiB delete bytes and 10,000 scanned entries per sweep.
- Unknown keys/types and invalid TTL/bounds fail strictly. Incomplete TTL cannot be shorter than terminal TTL. `dry_run=true` performs bounded discovery/validation/classification/planning without mutation.
- Only L3-owned marked artifacts are eligible. Legacy unmarked artifacts, final outputs, persisted SQL/ES results, manifests, aggregates, stage artifacts and logs are outside GC ownership.
- After the first deletion entry/byte budget exhaustion, validation/classification/counters continue for later candidates while deletion stays disabled for the rest of that sweep.
- Successful hierarchical final write with `cleanup_transient_on_success=true` invokes immediate eligible transient cleanup using effective transient TTL zero; set it false to retain successful runtime workspaces for the configured transient TTL.

### ES metadata safety

- Persisted model metadata is allowlisted. Credential-like keys, actual endpoint URLs, API keys/tokens/passwords/private keys and raw model specs must not be written into ES metadata.

## Recent Changes

### 2026-10-06 v1.1 transient semantic cache

- Added the strict root operational policy and bounded memory-only semantic-call memo contract while preserving persisted freshness/checkpoint authority.

### 2026-10-06 Closure documentation corrections

- Clarified that persisted semantic processing identity is opt-in and that prompt semantics influence the hash without persisting plaintext prompts.
- Clarified default immediate cleanup behavior for successful transient runtime artifacts.

### 2026-10-06 L3 reporting corrective

- PR #201 introduced the run-local deletion-budget latch and added regressions for later malformed tombstones and smaller artifacts encountered after byte-budget exhaustion.

### 2026-10-04 L2/L3 contracts

- Added explicit partial-success/cancellation taxonomy, production cancellation/observer contracts and safe retention/GC contracts.

### 2026-10-02 to 2026-10-03 K2/L1 contracts

- Added bounded nesting, prompt-aware input preparation, persisted processing identity and SQL/ES freshness/recheck contracts.

## Archived History

- `.codex/archive/api_contract.md-20261006-134200.md` — complete pre-compaction API/contract history through PR #200 head `39177737486a372f38e9b6d81563d6f14327459a`.
