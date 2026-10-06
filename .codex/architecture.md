# architecture

## Current Summary

- `czjLLM/prompt_pipeline/pipeline_controller.py` remains the compatibility/orchestration facade; focused runtime helpers live under `prompt_pipeline/runtime_support/`, while existing imports are preserved through re-exports.
- SQL/Table/ES producer row/document concurrency and prompt-slice concurrency are separate desired widths. The shared process-local `ExecutionBudget` is the hard leaf-execution ceiling and is intentionally excluded from semantic identity.
- `combine_utils.py` remains the compatibility boundary for Success discovery, output placement, final writes and legacy cleanup; JSON repair/combination and slice-merge logic live in focused modules.
- Row Merger remains downstream writeback coordination and Output Profile remains the final strict validation boundary. Reduction Core does not own either boundary.
- ES connection/pending behavior is separated into adapter, pending-policy and value-helper boundaries. Model metadata persistence uses allowlisted non-secret fields; credentials and raw endpoint URLs are excluded.
- Per-run LLM auditing records API usage tokens and context metadata from response/runtime/model sources. Context size is never guessed from a display name; CSV and XLSX artifacts are produced per run.
- Reduction Engine v1 A–L plus the L3 release-audit corrective are present at verified `main` merge `91e39503c8e84d17752f9d26a23ff6b34db75b9e`.
- Reduction flow is map/member execution → reducer → optional hierarchical rounds → final result → optional persisted aggregate/writeback. The core owns strict config, deterministic/semantic/structured-relational reducers, atomic checkpoints, shared execution budget, executable stages, explicit partial success and cooperative cancellation.
- Collection boundaries use immutable ordered `LogicalWorkUnit` / `CollectionManifest` snapshots. SQL/ES adapters build snapshots and idempotent aggregate sinks persist `AggregateOutput` using deterministic lineage identity.
- Persisted SQL/ES destination output is cross-run reuse authority when semantic freshness is explicitly configured. Runtime round workspaces are reconstructable; committed checkpoints are resume authority.
- Composition is bounded, not a generic DAG: one nested ReductionStage level, at most four active PipelineRef names, cycle detection, and no semantic reducer in a nested ReductionStage.
- Production cancellation is cooperative safe-drain. A run-scoped cancel intent stops new scheduling/semantic continuation while consumer/merger/writeback and already-running external calls reach safe boundaries.
- Production observability uses payload-free bounded JSONL, cumulative counters and a separate Reduction Status surface. Operational observer/cancellation state is excluded from semantic fingerprints.
- Retention is disabled by default, ownership/lease/claim based, bounded, symlink/containment guarded, and never adopts legacy unmarked artifacts. After deletion-budget exhaustion, later candidates still undergo validation/classification/counters but no further deletion is attempted.
- Successful hierarchical final writes use `cleanup_transient_on_success: true` by default, which performs the post-success transient cleanup path with effective transient TTL zero. Set it false to retain successful runtime workspaces for `transient_runtime_ttl_hours`.

## Recent Changes

### 2026-10-06 Reduction Engine v1 closure

- PR #201 corrected truthful bounded-retention reporting and merged as verified/valid `91e39503c8e84d17752f9d26a23ff6b34db75b9e`.
- PR #200 reconciles the operator/developer documentation against that baseline and remains documentation-only.

### 2026-10-04 Production hardening

- L2a established explicit partial-success policy and cooperative cancellation; only `ExecutionError` is recoverable member failure, while cancellation and programmer/system faults propagate.
- L2b bridged cancellation and production observability through SQL/Table/ES scheduling, prompt execution, reduction, writeback and GUI status.
- L3 added disabled-by-default safe retention with ownership markers, leases, claim/tombstone deletion, TTLs, scan/delete budgets and post-success transient cleanup.

### 2026-10-02 to 2026-10-03 Persisted freshness and bounded nesting

- K2 established one nested ReductionStage level, four active PipelineRef names, immutable depth/cycle guards and prompt-aware preparers.
- L1 kept SQL/ES persisted output as reuse authority and added opt-in semantic processing identity plus recheck observability.

### 2026-09-24 to 2026-10-01 Collection and reducer expansion

- Immutable collection identity, SQL/ES collection adapters, idempotent aggregate upsert, deterministic composite reducers, semantic reduction, structured-relational reduction and executable-stage composition were added without moving writeback ownership into Reduction Core.

### 2026-09-19 to 2026-09-20 Reduction foundation

- Reduction began as strict opt-in routing with source-agnostic reducer/controller/checkpoint contracts, then added fixed/adaptive hierarchical text reduction and the shared process-local execution budget.

## Archived History

- `.codex/archive/architecture.md-20261006-134200.md` — complete pre-compaction architecture history through PR #200 head `39177737486a372f38e9b6d81563d6f14327459a`.
- Historical point-in-time implementation notes that are superseded by the Current Summary remain traceable in that archive.
