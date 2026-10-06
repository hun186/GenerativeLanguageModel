# Architecture Decisions

## Current Summary

- `combine_utils.py` remains the compatibility facade for Success discovery/output placement/final writes; Row Merger remains writeback coordination and Output Profile remains final strict schema validation.
- Reduction is explicit opt-in and source-agnostic. Reduction rounds are not business Stages.
- Persisted SQL/ES destination results remain the sole v1 cross-run member-result reuse authority. No duplicate transient member-result cache was introduced.
- Semantic processing identity is opt-in at persisted destination boundaries. `auto` derives from effective Executable semantics; prompt/task semantics affect the hash while plaintext prompts, secrets and operational state are excluded from persisted fingerprint metadata.
- Caller-supplied collection ordering and immutable manifest identity are authoritative; aggregate sinks reject conflicting lineage.
- Bounded composition is deliberate: one nested ReductionStage level, at most four active PipelineRef names, explicit cycle/depth failure, and no nested semantic reducer.
- `require_all` remains the compatibility default. Partial success is explicit opt-in and only `ExecutionError` is recoverable; cancellation and programmer/system faults propagate.
- Operator cancellation is cooperative safe-drain. Producer cancellation and worker teardown are distinct; already-running HTTP calls are not forcibly killed.
- Cancellation/observer/retention/concurrency settings are operational and excluded from semantic fingerprints.
- Recheck Status and Reduction Status are separate observability surfaces; diagnostic JSONL is bounded and payload-free.
- Filesystem GC is disabled by default, ownership-based, bounded and conservative. Unmarked pre-L3 artifacts are never adopted; malformed state fails closed.
- Committed checkpoints are resume authority, runtime round directories are reconstructable, and L1 persisted SQL/ES output remains cross-run reuse authority.
- After deletion budget exhaustion, classification/reporting continues but deletion cannot resume later in the same sweep.
- `cleanup_transient_on_success=true` is the default post-success fast path; retaining successful runtime workspaces for the transient TTL requires disabling that option.
- Reduction Engine v1 A–L is complete. The L3 audit corrective is merged at verified `main` `91e39503c8e84d17752f9d26a23ff6b34db75b9e`; PR #200 remains documentation-only and unmerged pending exact-head gate/review and explicit merge approval.

## Recent Changes

### 2026-10-06 Closure decision

- PR #201 resolved truthful bounded-retention reporting and passed fresh 24/24 hosted acceptance before merge.
- PR #200 release-state declaration head `8d283b369da2989535c109fa4f046b2c7ba57f31` passed CI #463 / `37402351444`, offline job `112072129880`, collect 24 and full gate PASS / 100%.
- Subsequent review/documentation corrections must receive their own fresh exact-head gate before merge.

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
