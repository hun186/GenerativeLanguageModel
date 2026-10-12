# architecture

## Current Summary

- `czjLLM/prompt_pipeline/pipeline_controller.py` remains the compatibility/orchestration facade; focused runtime helpers live under `prompt_pipeline/runtime_support/`, while existing imports are preserved through re-exports.
- SQL/Table/ES producer row/document concurrency and prompt-slice concurrency are separate desired widths. The shared process-local `ExecutionBudget` is the hard leaf-execution ceiling and is intentionally excluded from semantic identity.
- `combine_utils.py` remains the compatibility boundary for Success discovery, output placement, final writes and legacy cleanup; JSON repair/combination and slice-merge logic live in focused modules.
- Row Merger remains downstream writeback coordination and Output Profile remains the final strict validation boundary. Reduction Core does not own either boundary.
- ES connection/pending behavior is separated into adapter, pending-policy and value-helper boundaries. Model metadata persistence uses allowlisted non-secret fields; credentials and raw endpoint URLs are excluded.
- Per-run LLM auditing records authoritative API usage tokens/context metadata plus optional local prompt-component token estimates. Context size is never guessed from a display name; CSV/XLSX artifacts are produced per run. The Windows GUI polls the current run CSV for a default-collapsed distribution view, while numeric-only prompt-component handoff metadata lives outside TODO/RUNNING so it cannot enter the prompt queue.
- Reduction Engine v1 A–L plus the L3 release-audit corrective and documentation closure are present at verified `main` merge `99d79676b16b7fed54f9cf6e701441db79846cea`.
- Reduction flow is map/member execution → reducer → optional hierarchical rounds → final result → optional persisted aggregate/writeback. The core owns strict config, deterministic/semantic/structured-relational reducers, atomic checkpoints, shared execution budget, executable stages, explicit partial success and cooperative cancellation.
- Collection boundaries use immutable ordered `LogicalWorkUnit` / `CollectionManifest` snapshots. SQL/ES adapters build snapshots and idempotent aggregate sinks persist `AggregateOutput` using deterministic lineage identity.
- Persisted SQL/ES destination output is cross-run reuse authority when semantic freshness is explicitly configured. Runtime round workspaces are reconstructable; committed checkpoints are resume authority. A v1.1 evaluation deliberately deferred any second semantic/member result cache until measured duplicate-call evidence exists.
- Composition is bounded, not a generic DAG: one nested ReductionStage level, at most four active PipelineRef names, cycle detection, and no semantic reducer in a nested ReductionStage.
- Production cancellation is cooperative safe-drain. A run-scoped cancel intent stops new scheduling/semantic continuation while consumer/merger/writeback and already-running external calls reach safe boundaries.
- Production observability uses payload-free bounded JSONL, cumulative counters and a separate Reduction Status surface. Operational observer/cancellation state is excluded from semantic fingerprints.
- v1.1 adds one optional Python-only final-result quality/coverage hook at the `ReductionStage` boundary. The hook receives the final payload plus existing safe stage metadata, returns scalar quality metrics/warning codes or an explicit rejection, and contributes its semantic metadata to fingerprints without introducing a scorer registry/YAML platform.
- Retention is disabled by default, ownership/lease/claim based, bounded, symlink/containment guarded, and never adopts legacy unmarked artifacts. After deletion-budget exhaustion, later candidates still undergo validation/classification/counters but no further deletion is attempted.
- Successful hierarchical final writes use `cleanup_transient_on_success: true` by default, which performs the post-success transient cleanup path with effective transient TTL zero. Set it false to retain successful runtime workspaces for `transient_runtime_ttl_hours`.

## Recent Changes

### 2026-10-08 LLM token/context distribution observability

- Added local task-text/template/rendered-prompt token estimates at prompt-generation time and keeps API usage authoritative for input/output/context occupancy. Multi-stage prompt replacement refreshes the numeric metadata for the actual dispatched prompt and clears stale metadata on count failure.
- A daemon audit-reader thread inside the Windows GUI process checks the append-only per-run audit CSV at a throttled cadence and performs CSV parsing plus distribution calculation off the Tk event loop. Tk only consumes completed snapshots, preserving progress/log/Cancel responsiveness while rendering default-collapsed token/context plus prompt-backed Slice latency distributions.

### 2026-10-06 v1.1 final quality/coverage hook

- Added a single final-stage task-specific quality policy extension point rather than a generic evaluator framework.
- No-hook behavior/fingerprint remains compatible; configured hook semantics are fingerprinted, accepted metrics are nested under result metrics/audit, and rejection is explicit.

### 2026-10-06 v1.1 cache-boundary evaluation

- Reaffirmed a single authority per retry scope: persisted SQL/ES results for cross-run reuse and committed checkpoints for hierarchical resume.
- Deferred transient semantic/member caching because current code/tests do not demonstrate a material duplicate-call workload. Any future cache must be opt-in, bounded, run-scoped, non-persistent by default, and operational rather than semantic authority.

### 2026-10-06 Reduction Engine v1 closure

- PR #201 corrected truthful bounded-retention reporting and merged as verified/valid `91e39503c8e84d17752f9d26a23ff6b34db75b9e`.
- PR #200 reconciled the operator/developer documentation and merged as verified/valid `99d79676b16b7fed54f9cf6e701441db79846cea`.

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

### 2026-10-12 GUI request throughput observability (proposed)

- The append-only audit schema can capture provider-reported cached input token counts, with a distinct source marker; missing provider cache metadata is unknown, not zero. Current `processing_tps` remains backward compatible; GUI derives `(input_tokens + output_tokens) / elapsed_seconds` for actual slice requests with positive elapsed.
- Local token sidecars add only an allowlisted stage identity (never task/prompt payload). The GUI off-thread CSV reader computes cache-adjusted throughput from provider truth where present and an explicitly discounted stable-template-size proxy only after same-stage history exists; no new persistence, service, prompt transfer, or cache-hit truth source is created.
- Histograms include collision-pruned min/P50/P95/max ticks and a 3+4 chart layout. Tk redraw and hover both use shared width/height bounds.
