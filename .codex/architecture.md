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
- v1.1 lineage convenience helpers are pure read-only projections/comparisons of the canonical aggregate mapping, validating the existing deterministic aggregate ID; they never serve as a second truth or interfere with sink conflict/freshness policies.
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

### 2026-10-13 Issue #211 E2E verification boundary (PR #213, pending)

- SQL and Table input modes share the production scheduler, direct multistage extract processing, stage manifest, row merger and physical sink. A first extract stage using the same input column as the primary row can safely reuse already-rendered per-slice prompts rather than rerender the entire source once per slice. This preservation is scoped to single-extract JSON stage writeback; alternate input-column routing and genuine multistage behavior stay untouched.
- New offline end-to-end tests use localhost fake OpenAI responses and deterministic cut positions, but real SQLite files, XLSX files, prompt queue and production writeback to verify output readback. No live provider/SQL Server is involved.

### 2026-10-14 partial extract resume authoritative source snapshots (PR #213 pending)

- For the single-extract JSON stage writeback path, the first unpruned input queue establishes the ordered raw-source-slice-to-filename mapping. A durable SHA-256-only provenance manifest in the original snapshot folder records both source/slice identities and actual dispatched prompt hashes with an effective stage-task digest.
- Later partial resumes reconstruct source slices and verify the existing complete snapshot, even after Success removes A from TODO. Completed members' recorded dispatch hashes reenter the final mandatory Success validation; partial or stale source and stage-task changes fail closed. Verified split child TODO prompts can survive original snapshot validation without being falsely treated as new raw slices.
- No second cache, alternative source of model results or changed public output schema was introduced. Scope remains strictly the original single extract / SQLite-Excel writeback flow.

### 2026-10-14 resilient single-extract source identity for smart_reset (PR #213)

- Hash-only raw source and dispatch provenance lives under `<item>/_extract_slice_identity/source/original.json`, not `_stage_outputs`, because `smart_reset` intentionally deletes all stage snapshots. Full raw-source fragments can be safely regenerated only after validating the source hash, ordered part hashes, and original filename mapping. These regenerated texts remain transient in `_stage_outputs/original`.
- The existing success and split identity directories remain authoritative for completed/retried prompts. When partial source membership cannot be verified, reject writeback rather than silently omitting Success siblings.


### 2026-10-20 Processing Quality observation boundary (PR #218)
- `czjLLM/utilities/processing_quality.py` defines a quality event stream adjacent to the per-run LLM call-audit CSV. `handle_json_output` emits slice-first-pass JSON and JSON-repair decisions. Row Merger emits terminal document schema rejection and successful writeback decisions only after the configured sink's confirmation.
- `QualityTailReader` incrementally reads complete JSONL lines off the Tk thread; `win_gui.py` displays an independent collapsed Processing Quality summary and type counts instead of mixing with the LLM Token/Context histogram. No source payload is stored.

### 2026-10-20 offline read-only quality report (separate PR)
- `cli_tools.processing_quality_report` reads only one existing run-scoped quality JSONL or enumerates a bounded history in its existing audit directory via `QualityTailReader` / `QualityAccumulator`. No new event producer/storage or runtime/GUI/prompt/sink mutation. Optional summary file uses `utilities.atomic_io.atomic_write_json`.


### 2026-10-23 Consumer-quality telemetry (new PR, unmerged)

- Legacy `llm_stream_consumer` sends observed scheduler/termination failures through the existing nonblocking quality JSONL writer; the same reader, GUI and offline CLI surface an independent event count. No new sink or per-document failure inference; stage-managed workers are not instrumented in this incremental scope.

### 2026-10-23 Stage orchestration observation boundary (new P2 PR, pending acceptance)

- The active multi-stage pipeline in `pipeline_controller.py` calls `stage_orchestrator.run_stage_pipeline` / `execute_stage_round`. Stage task routing and input preparation, followed by a compatible 3-argument or 2-argument Runner invocation, are the new bounded observation sites. Their escaping non-cancellation exceptions use existing `processing_quality` per-run JSONL; no replay/exception policy, checkpoint ownership or result shape is changed. GUI, accumulator and offline reports project the same events and never count them as failed documents or LLM requests.

### 2026-10-24 leaf Worker phase observations (P2 PR pending)

- The actual `PromptAPIPipeline.proc()` boundary (used in leaf jobs, including multiprocess execution) now records bounded `worker_phase_failure` observations in its established caught-exception path based solely on the current execution phase. Before-call endpoint selection, during `CallLLMAPI` invocation, after-return response/JSON handling and Success file/identity persistence are distinct sites; they are not provider root-cause classifications.
- Existing Worker error dict, per-request CSV, per-slice repair auditing and Stage orchestrator exception auditing remain independent; overlapping incidents across layers may occur and do not represent unique failed documents. Shared Processing Quality reader, offline report and GUI project the one existing JSONL authority.

### 2026-10-24 typed OpenAI SDK exception classification (proposed PR)

- `CallLLMAPI` remains the source of actual SDK request execution and legacy timeout/connection `RuntimeError` wrapping. New pure `classify_llm_call_exception(error)` checks only the SDK exception's type, HTTP `status_code`, or the direct SDK cause of a legacy `RuntimeError`; no error-string interpretation or network inspection.
- `PromptAPIPipeline.proc()` still owns its single caught-error Worker run event: for its existing `WORKER_LLM_CALL_EXCEPTION` execution phase only, call the classifier and emit exactly one more-specific `worker_phase_failure` code or the old generic code. Existing CSV and JSONL stream authorities, document denominators, GUI count, cancellation and persistence are unchanged.


### 2026-10-24 run-only incident drilldown projection (pending PR)

- New `RUN_INCIDENT_CODES` is derived from existing `_EVENT_CODES` and `_EVENT_SCOPES`; report modules never invent an independent/possibly stale Worker SDK code list.
- The existing `QualityTailReader` performs privacy/error-code validation, deduplication and corrupt-line observation. `run_incident_diagnostics(stats, family=...)` is a pure read-only projection of its accepted fixed-code counts, optionally narrowing only the displayed run-scoped family details. Per-run observed-incident denominator remains the whole run, with null share when zero. History never pools per-run denominators. No additional parser, log write, I/O authority or DB/model service.


### 2026-10-24 manual archive rotation and offline multi-file replay (unmerged PR)

- Existing run quality JSONL active path and `.jsonl.lock` remain the only emit targets; an opt-in maintenance command reuses the same cross-process lock and atomically renames complete active files to numbered immutable `.jsonl.seg-NNNNNNNN` paths. Neither scheduled rotation nor automated retention/deletion exists.
- A separate bounded (64) archive-discovery module enumerates strict consecutive numbered segments, refusing gap/malformed names and symlinks. Offline reports replay archive segments in sequence followed by the optional current active file; all `QualityTailReader` instances share one `QualityAccumulator` for cross-generation event ID dedup and document decision reconciliation. GUI continues using the unchanged single-active-file reader; no full live-resume claim.


### 2026-10-24 opt-in sealed-archive SHA256 consistency ledger (unmerged PR)

- Keep the original `processing_quality_events_<run>.jsonl` writer, lock and manual numbered shard scheme unchanged. A distinct `processing_quality_manifest` module hashes only sealed `.jsonl.seg-NNNNNNNN` archive bytes via bounded memory descriptor reads, recording sequence, byte size and digest; small schema-checked `.jsonl.manifest.json` is atomically published under the writer lock.
- Manifest initialization against legacy archives is explicitly opt-in (stopped producer); no implicit baseline or archival deletion. Once sealed, manual rotation prechecks the existing manifest, renames its active file, publishes an updated ledger, and attempts rollback on publish failure. Offline report validates sealed bytes before and after existing shared-accumulator replay and discovers manifest-only missing-run records. Unsealed legacy history is reported as unsealed, not silently called verified.


### 2026-10-24 GUI cross-archive quality reader (new independent PR)

- `win_gui._quality_reader_worker` still handles all I/O and parsing outside Tk, but now delegates to `QualityRunTailReader` rather than a standalone active-only `QualityTailReader`. On initial load, archived numbered files and optional live active file share a single validated `QualityAccumulator`. On stable generations, only the active append tail is polled; archive and ledger identities are bounded metadata checks, not full SHA-256 on every 1s poll.
- When archived shard metadata, ledger metadata, or active file generation changes, the wrapper replays verified archives and active through one new accumulator off-Tk. Tampered missing archives, partial archived shard and unsafe symlink fail closed. The GUI receives a fixed `quality_stream_status`, not any raw path/exception text. The existing manual rotation CLI remains stopped-producer-only; GUI cross-shard visibility is not approval for online rotation.


### 2026-10-25 GUI-quality read-only cardinality and line budgets (new independent PR)

- `QualityAccumulator` accepts optional positive `max_events` and `max_identity_chars`; `QualityTailReader` accepts optional positive `max_line_bytes`. Defaults remain unlimited for existing offline reports, and shared-accumulator semantics stay unchanged. A rejected event is never admitted into the dedup map, document sets or counters; a failed read never advances a tail offset. Accumulator reset preserves its caps.
- `QualityRunTailReader` uses a per-run default 50,000 accepted unique events, 4,000,000 approximate retained event/document identity characters and 64 KiB per-line limit across all archived and active JSONL generations. This bounds some per-run GUI allocations but **is not a physical RSS guarantee**. An over-budget input raises a distinct capacity error; the GUI worker replaces metrics with an explicit unavailable status, does not emit incomplete percentages, leaves original files alone and suggests full offline report. No automatic retention, archive prunes, schema changes or producer interruptions.


### 2026-10-25 unchanged over-budget GUI run polling

- `QualityRunTailReader.poll()` keeps a small `_capacity_generation` (archive file stat identities, Manifest stat identity, active stat identity) when `QualityCapacityExceeded` occurs and the metadata remains unchanged across the failed read. Stable, failed generation yields immediate capacity error on subsequent polls; no archive hash or expensive event replay occurs. When metadata changes, reconstruction is retried, and successful stats clear the capacity marker. Once the reader observed archive count, subsequent unexplained historical shrink also fails closed, even if the initial rebuild did not finish. The worker still publishes an unavailable, privacy-minimal capacity warning.


### 2026-10-25 capacity retry state vs established filesystem history

- `_capacity_generation` is evictable metadata cache used solely to avoid expensive repeated failed replay. Separately, `_observed_archive_count` and `_observed_active_identity` retain evidence of previously seen historical files even if a metadata race invalidates the capacity shortcut. When a formerly present active disappears, a new canonical archive must preserve its device/inode identity with nondecreasing size to count as a safe rotation; otherwise status is unavailable. Commit these observed-history fields on successful read or definite over-budget failure, not on malformed/invalid archived or manifest generations, so repairing a temporary invalid extra shard remains possible.

### 2026-10-27 optional offline SQLite temporary identity spill (unmerged)

- `processing_quality_disk_spill.DiskBackedQualityAccumulator` reuses QualityAccumulator's event validation, code taxonomy and privacy-safe in-memory counters while substituting private ephemeral SQLite-backed exact event-ID/signature and rejected/confirmed document membership. Its aggregate snapshot queries pending/confirmed cardinality without materializing the full union/difference in Python RAM.
- Only the offline report CLI opt-in `--disk-backed` constructs this backend; each single-run/history item gets a new scoped temporary index. It is closed and removed on success and exceptions, and refuses source resets rather than presenting partial history. GUI/Tk and producers keep the unchanged in-memory implementation; ledger integrity checks still surround replay. No archival mutation, retention or restart checkpoint.

### 2026-10-27 isolated offline quality report benchmark (unmerged)

- `czjLLM.cli_tools.processing_quality_benchmark` accepts one canonical audit CSV path and child-process repetitions. Each fresh `sys.executable -m ... --worker` subprocess reads the path and mode via bounded JSON stdin, executes existing `report_for_audit()`, hashes the *complete* canonical aggregate report, measures elapsed, tracemalloc peak and platform high-water RSS. It instruments the SQLite backend only in the private child to measure final temporary main database size immediately before cleanup.
- Parent aggregates sample medians; a differing digest on any sample raises rather than claiming performance comparison. No raw document/event IDs, paths, payloads or temp identities leave the child; no new permanent DB or retained source. Source immutability is an operator precondition, not a cryptographic lock.
