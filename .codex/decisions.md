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
