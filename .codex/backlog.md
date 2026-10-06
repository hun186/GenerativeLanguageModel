# 待辦事項（Backlog）

## Current Summary

**Reduction Engine v1 = COMPLETE / RELEASE-READY.** A–L is complete, the L3 release-audit reporting blocker was resolved by PR #201, and the documentation/release closure was merged by PR #200. Authoritative `main` baseline: verified merge `99d79676b16b7fed54f9cf6e701441db79846cea`.

PR #200 is closed/merged. Its accepted exact head `36a40eb37827e33545865203b079aefaab1ba1f4` passed CI #467 / `37420475520`, offline job `112128483703`, collect 24 and full gate PASS / 100%, with zero unresolved review threads and a fresh Codex review reporting no major issues.

### Reduction Engine v1 roadmap

- [x] PR A — Characterization / Golden Tests
- [x] PR B — Contracts, Reducer Registry, legacy adapters
- [x] PR C — Strict config + opt-in single-pass routing
- [x] PR D — Hierarchical reduction (D1/D2)
- [x] PR E — Shared Execution Budget
- [x] PR F — Logical Work Unit + immutable Collection Manifest
- [x] PR G — SQL/ES Collection Adapters + idempotent aggregate upsert
- [x] PR H — Deterministic composite reducers
- [x] PR I — Semantic reducer
- [x] PR J — Structured relational reducer
- [x] PR K — ReductionStage + bounded PipelineRef nesting (K1/K2)
- [x] PR L — Production hardening (L1/L2a/L2b/L3)

## Open Follow-ups

### Future v1.1 candidates — not v1 blockers

- [x] Evaluate optional transient semantic/member caching only with a distinct authority/privacy contract; **decision: defer implementation until production evidence shows material duplicate member/semantic execution. No persistent second cache is allowed; SQL/ES persisted output and committed checkpoints retain their existing authority.**
- [ ] Add task-specific quality/coverage hooks without creating a generic evaluation platform.
- [ ] Consider aggregate-lineage convenience APIs beyond the complete v1 `AggregateOutput` payload lineage contract.
- [ ] Consider explicit maintenance/migration tooling for legacy unmarked stage artifacts; v1 GC intentionally never adopts them.
- [ ] Consider finer checkpoint coordination if production evidence justifies replacing conservative per-executable serialization.

### Existing technical-debt follow-up

- [ ] Evaluate whether `utils/utilities.py` remains an active dependency; if so, progressively move responsibilities into focused utility modules while retaining compatibility re-exports.

## Recent Changes

### 2026-10-06 v1.1 transient-cache evaluation

- [x] Evaluated a second transient semantic/member cache against the current execution, checkpoint, persisted-freshness, cancellation and privacy contracts.
- [x] Deferred implementation: current source/tests do not establish a material duplicate-call workload that justifies new cache semantics.
- [x] Any future reconsideration requires production duplication/cost evidence and a bounded run-scoped privacy contract; disk/global persistence must not become a second reuse authority.

### 2026-10-06 Release-audit closure

- [x] L3 truthful bounded-reporting blocker resolved by PR #201.
- [x] Accepted PR #201 head `62deba6a35d5d5f1d5c82f586d65bc8827e212ef`; CI #459 / `37399753801`; offline job `112064086574`; collect 24; full gate PASS / 100%; merge `91e39503c8e84d17752f9d26a23ff6b34db75b9e`; signature verified / valid.
- [x] PR #200 release-state declaration head `8d283b369da2989535c109fa4f046b2c7ba57f31` passed CI #463 / `37402351444`, offline job `112072129880`, collect 24 and full gate PASS / 100%.
- [x] PR #200 accepted head `36a40eb37827e33545865203b079aefaab1ba1f4`; CI #467 / `37420475520`; offline job `112128483703`; collect 24; full gate PASS / 100%; zero unresolved review threads; fresh Codex review reported no major issues; merged as verified/valid `99d79676b16b7fed54f9cf6e701441db79846cea`.

## Archived History

- `.codex/archive/backlog.md-20261006-134200.md` — complete pre-compaction backlog/history through PR #200 head `39177737486a372f38e9b6d81563d6f14327459a`. Historical unchecked K/L entries in that archive are superseded by the completed roadmap above.
