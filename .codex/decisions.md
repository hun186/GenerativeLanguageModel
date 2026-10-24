# Architecture Decisions

## Current Summary

- `combine_utils.py` remains the compatibility facade for Success discovery/output placement/final writes; Row Merger remains writeback coordination and Output Profile remains final strict schema validation.
- Reduction is explicit opt-in and source-agnostic. Reduction rounds are not business Stages.
- Persisted SQL/ES destination results remain the sole cross-run member-result reuse authority. A v1.1 evaluation explicitly deferred any transient semantic/member cache until measured duplicate-call evidence justifies it; no persistent/global second cache may become an authority.
- Semantic processing identity is opt-in at persisted destination boundaries. `auto` derives from effective Executable semantics; prompt/task semantics affect the hash while plaintext prompts, secrets and operational state are excluded from persisted fingerprint metadata.
- Caller-supplied collection ordering and immutable manifest identity are authoritative; aggregate sinks reject conflicting lineage.
- Bounded composition is deliberate: one nested ReductionStage level, at most four active PipelineRef names, explicit cycle/depth failure, and no nested semantic reducer.
- `require_all` remains the compatibility default. Partial success is explicit opt-in and only `ExecutionError` is recoverable; cancellation and programmer/system faults propagate.
- Operator cancellation is cooperative safe-drain. Producer cancellation and worker teardown are distinct; already-running HTTP calls are not forcibly killed.
- Cancellation/observer/retention/concurrency settings are operational and excluded from semantic fingerprints.
- A configured task-specific quality hook is semantic because it can accept/reject the final result; its contract/config metadata therefore participates in the stage execution fingerprint. No-hook fingerprints remain unchanged.
- Recheck Status and Reduction Status are separate observability surfaces; diagnostic JSONL is bounded and payload-free. LLM token/context distributions are a third default-collapsed GUI observability surface sourced from the run audit CSV, not a new execution authority.
- Filesystem GC is disabled by default, ownership-based, bounded and conservative. Unmarked pre-L3 artifacts are never adopted; malformed state fails closed.
- Committed checkpoints are resume authority, runtime round directories are reconstructable, and L1 persisted SQL/ES output remains cross-run reuse authority.
- After deletion budget exhaustion, classification/reporting continues but deletion cannot resume later in the same sweep.
- `cleanup_transient_on_success=true` is the default post-success fast path; retaining successful runtime workspaces for the transient TTL requires disabling that option.
- Reduction Engine v1 A–L is complete. The L3 audit corrective merged at `91e39503c8e84d17752f9d26a23ff6b34db75b9e`, and PR #200 documentation/release closure merged at verified `main` `99d79676b16b7fed54f9cf6e701441db79846cea`.

## Recent Changes

### 2026-10-08 LLM audit GUI decision

- Keep API-reported input/output usage authoritative; local tokenizer counts for task text/template overhead are observability estimates only.
- Drive GUI distributions from the append-only audit CSV instead of sending per-call token/latency payloads over GUI IPC.
- Keep prompt-component handoff numeric-only and outside TODO/RUNNING; every rendered multi-stage prompt refreshes its basename metadata, and refresh failure clears stale values rather than reusing them. Unavailable component metrics remain unknown rather than inferred from API totals.
- Treat `elapsed_seconds` as per-slice LLM latency only when the audit row has a nonblank `prompt_file`; direct JSON repair calls remain valid audit rows but are not slice-latency samples.

### 2026-10-06 v1.1 quality-hook decision

- Use one optional Python-only final-result hook on `ReductionStage`; do not add a universal quality scorer, registry, YAML schema, model judge, or UI.
- Restrict returned assessment metadata to safe scalar metrics and warning codes. Payload inspection is transient inside caller hook code and is not copied into audit/metrics.
- Rejection is explicit and fail-closed; hook metadata is semantic/fingerprinted because it can change acceptance.

### 2026-10-06 v1.1 transient-cache decision

- Do not add a disk/global semantic or member-result cache: that would duplicate persisted reuse authority and enlarge source-derived data retention/privacy scope.
- Do not add a run-memory cache merely because it is technically possible. Reopen only when production telemetry or reproducible workloads show material duplicate same-semantics execution/cost.
- If reopened, the acceptable starting shape is opt-in + bounded + run-scoped + non-persistent by default; cache only successful immutable execution results; keep cache policy/state outside semantic fingerprints; preserve cancellation, partial-failure, observer and accounting semantics.

### 2026-10-06 Closure decision

- PR #201 resolved truthful bounded-retention reporting and passed fresh 24/24 hosted acceptance before merge.
- PR #200 release-state declaration head `8d283b369da2989535c109fa4f046b2c7ba57f31` passed CI #463 / `37402351444`, offline job `112072129880`, collect 24 and full gate PASS / 100%.
- Subsequent review/documentation corrections received their own fresh exact-head gate on `36a40eb37827e33545865203b079aefaab1ba1f4`, then PR #200 merged as verified/valid `99d79676b16b7fed54f9cf6e701441db79846cea`.

### 2026-10-04 L2/L3 decisions

- Keep partial success explicit, preserve exception taxonomy, use cooperative cancellation, and keep observability payload-free.
- Keep GC operational, disabled by default, claim-before-delete and outside authoritative persisted result/manifest/final-output ownership.

### 2026-10-02 to 2026-10-03 K2/L1 decisions

- Prompt-aware preparation must use the authoritative production rendering/tokenization boundary; checkpointed nested execution is conservatively serialized.
- Persisted freshness derives from existing Executable metadata and binds once before discovery; SQL identity-column collisions fail configuration and ES required-output correctness may override query optimization.

### 2026-09-19 to 2026-10-01 foundation decisions

- Reduction was delivered incrementally: strict opt-in routing → hierarchical checkpoints → shared execution budget → immutable collection identity/adapters → deterministic/semantic/relational reducers → executable stages and bounded nesting.

## Archived History

- `.codex/archive/decisions.md-20261006-134200.md` — complete pre-compaction decision history through PR #200 head `39177737486a372f38e9b6d81563d6f14327459a`.
- Earlier archive references remain preserved inside that snapshot.

### 2026-10-13 Issue #211 SQL/Excel E2E test decision (PR #213, pending)

- Mock only the external model HTTP response and initial tokenization cut boundaries; assert production scheduling, stage validation, merged stage writeback and physical SQLite/XLSX readback. Add explicit partial-resume case using persisted Success provenance and real remaining-leaf provider dispatch.
- Preserve existing per-slice primary-input prompts during scoped single-extract stage preparation instead of rendering one full SQL/Excel row prompt for each slice. No change to alternate source-column routing.

### 2026-10-14 extract partial-resume provenance (PR #213 pending)

- Prefer one persisted, source-bound original input-slice identity over reassigning raw chunks to whatever TODO files happen to remain after interrupted processing. Treat source SHA, ordered chunk fingerprints, saved filenames and dispatched prompt/stage identity together as the reuse contract; stale or ambiguous evidence must reject writeback.
- Preserve committed retry child prompts by verifying split lineage; do not rerender the parent source as a child's independent prompt.

### 2026-10-19 multidim Event output schema correction policy (PR #216)
- For cross-slice metadata, treat article_date_iso and article_date_precision as ONE atomic source-provenance pair; never compose a date from one slice with a precision from another. Preserve existing scalar conflict preference and conservative unknown/null instead of favoring a date merely because it exists in a later slice. Treaty/event signing dates are not document publication metadata without explicit source evidence.
- ES strict multidim output contract may perform lossless shape normalization of the five explicitly documented importance score keys found at top-level, but never recompute a score, silently overwrite conflicting existing nested values or allow unknown keys. Generic JSON processing remains unchanged.
- Retain strict fail-closed Event local links and schema errors, requiring bounded real ES acceptance after unit/CI and code review.


### 2026-10-20 separate processing-quality observability (PR #218)
- Keep slice validation and JSON repair attempt rates separate from distinct document writeback decisions to avoid treating recovered syntax errors as failed documents, or treating a released pending row as successful ES writeback.
- Prefer structured events emitted at decision points over parsing console warnings; append minimal metadata to a separate per-run JSONL with a cross-process file lock; render a collapsed GUI section with a background reader independent of token/context distribution.
- Do not automatically interrupt a large batch based on a raw event count; alerts require a denominator and minimum sample size.

### 2026-10-20 offline continuation without LLM
- Preserve tomorrow's real acceptance baseline on merged #218 main; new work belongs in separate unmerged branch. Implement offline quality history/export as a read-only projection of the single existing JSONL event authority rather than introducing another log writer or shadow counters. A denominator below 30 is advisory only; it does not gate acceptance, and unknown stays null.

- Corrupt newline-complete JSONL lines are surfaced as a degraded completeness warning, not silently absorbed into a successful report or counted in quality denominators. This change is read-only, backward compatible for old reader clients, and explicitly observable in offline reports.

- Incremental quality reader retains O(1) bounded reread on each poll (first/last 512 committed bytes), detecting common in-place rewrites/rotation while preserving large log performance; avoids mislabeling valid repeated event IDs as malformed. If an adversarial rewrite changes only unmonitored interior bytes, offline reports cannot prove integrity and need a separate durable manifest/hash contract, not a made-up success signal.

- A syntactically valid record must have a semantically matched event/code and (where present) scope; document events require a nonblank document_id. This prevents incomplete input from falsely raising `events` without affecting the relevant denominator. Deprecated test fixtures without explicit scope remain backward compatible.

- The quality audit reader now keeps a compact per-event canonical hash as its duplicate identity instead of only a set of event IDs: exact replays remain idempotent, but conflicting content with reused ID is explicitly degraded. Generation reset is a published state change so a status UI cannot persist obsolete counts when zero replacement events exist.

### 2026-10-23 Producer operational observability boundary (P2 PR proposal)

- Instrument catch-site exceptions rather than parse console messages or infer failure from a schedule returning zero. Mark operational events run-scoped with fixed enums, no row/stage identity or source content. Do not change cancellation, pending-row skip, ordinary schedule-noop semantics or multistage Future behavior.
- Existing per-run JSONL writer and reader remain the only event authority; GUI is a projection. No new persistent store or request/document failure-rate denominator. Stage Worker and lifecycle/retention remain separate so this PR's scope stays reviewable.

### 2026-10-23 Producer cooperative cancellation error priority (PR #224 P2 corrective)

- Cooperative `ExecutionCancelled` is authoritative for Producer control flow. Best-effort Pending Console cancellation cleanup may log only exception type on failure, but must never convert cancellation to a generic `Future.result()` exception, emit `PRODUCER_FUTURE_EXCEPTION`, or mark the run as not cancelled. Attempt each cleanup step independently even if the other fails.

### 2026-10-23 Stage instrumentation scope decision (P2 PR pending)

- Instrument actual Stage orchestration task/input resolution and Runner invocation failure boundaries; do not parse console logs, infer any Stage error from failed model responses, or mislabel generic escaped Runner exceptions as specifically provider or non-provider failures. Preserve historical two-argument fallback and cancellation propagation; best-effort JSONL audit cannot replace the primary exception.
- Keep observability run scoped and payload/identity free, using the existing quality reader, GUI and read-only offline reports. Worker root-cause detail, filters and event retention remain separate work.

### 2026-10-24 leaf Worker execution site classification decision

- Use a fixed enum set by control flow before the external model call, while running the call, after its successful return, or while persisting Success/identity. Avoid user-provided exception messages, class-name guessing, model URLs or any stage/input/prompt ID as an event field. Do not label every call-site exception a provider failure.
- A run-scoped leaf Worker phase event and a request CSV entry can both describe one failure; do not aggregate them into distinct failed documents. Keep the historical caught-error return, CSV row finalization, mock-only behavior and cancellation handling unchanged. Emitter failure is best effort and cannot replace original Worker results.

### 2026-10-24 SDK failure subtype policy

- Reuse one existing `worker_phase_failure` run-only event rather than issuing a second SDK event per caught exception. Only refine the previously established `WORKER_LLM_CALL_EXCEPTION` phase, using SDK exception classes and verified `APIStatusError.status_code`; do not infer from localized error text, URLs, regular expressions or arbitrary `RuntimeError`.
- Distinguish 429 vs HTTP 5xx vs 4xx (with generic fallback); preserve original `CallLLMAPI` exception/return and legacy CSV. A classifier failure is best effort and must never mask the original Worker failure. Categorize mechanisms as evidence, not remote-model blame.


### 2026-10-24 incident drilldown scope policy

- Deliver fixed-code, run-only **read-only reporting** first: the JSONL `QualityTailReader` remains sole authority for valid/duplicate events and corrupt line status. Filter accepted counts from the same mapping as the emitter/parser, never parse exception text, URLs or source IDs and never reread raw source to extract "examples".
- CLI family focus is an allowlisted *presentation projection*; retain unfiltered metric counters and the denominator of all observed run-scoped incidents. Show unknown percent on zero denominator and low-sample advisory. No new persistent store, event schema or cross-run aggregation; lifecycle/rotation and operator-specific privacy/redaction improvements remain future work.


### 2026-10-24 JSONL lifecycle phase 1 no-delete boundary

- Start with **opt-in manual rotation after operator stops writers/readers**, not online timer or automatic retention. Reuse the producer's cross-process append lock, same-directory atomic rename and consecutive numbered archives without rewriting or deleting any accepted event; reject partial last records, gaps and archive budget exhaustion.
- Extend existing offline report with shared-accumulator replay instead of summing per-file aggregates (which would double-count event IDs and lose document reject→confirmed recovery). Keep GUI single-live-file view as a disclosed limitation. Only introduce destructive retention and real live readers with separate consistency/manifest protocol and independently tested rollback/partial-failure semantics.


### 2026-10-24 archive integrity ledger trust boundary

- Choose manual opt-in trust-on-first-use SHA-256 sidecar over automatic migration of legacy archives; avoid falsely asserting past integrity. Hash immutable numbered archives only, not concurrently growing active JSONL. Retain original append lock and no-delete rotation; write metadata via same-directory atomic replace with fsynced payload, roll back rename on publication errors where safe.
- Verify sealed archive count and hashes both before and after offline multi-shard replay. A ledger mismatch fails closed rather than reset or inferred successful migration; retain existing strict event schema, duplicate ID and per-document recovery semantics. Explicitly distinguish self-consistency from authenticated evidence, defer signed manifests, crash recovery, automated retention and GUI continuity.
