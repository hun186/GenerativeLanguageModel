# 待辦事項（Backlog）

## Current Summary

**Reduction Engine v1 = COMPLETE / RELEASE-READY at the runtime/product-contract level.** A–L is complete and the L3 release-audit reporting blocker is resolved by PR #201. Authoritative runtime baseline: verified `main` merge `91e39503c8e84d17752f9d26a23ff6b34db75b9e`.

PR #200 remains documentation-only and unmerged. Its current documentation head must receive a fresh exact-head hosted 24-case gate and fresh review after every corrective commit before it is marked merge-ready; explicit user merge approval is still required.

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

- [ ] Evaluate optional transient semantic/member caching only with a distinct authority/privacy contract; persisted SQL/ES output remains v1 reuse authority.
- [ ] Add task-specific quality/coverage hooks without creating a generic evaluation platform.
- [ ] Consider aggregate-lineage convenience APIs beyond the complete v1 `AggregateOutput` payload lineage contract.
- [ ] Consider explicit maintenance/migration tooling for legacy unmarked stage artifacts; v1 GC intentionally never adopts them.
- [ ] Consider finer checkpoint coordination if production evidence justifies replacing conservative per-executable serialization.

### Existing technical-debt follow-up

- [ ] Evaluate whether `utils/utilities.py` remains an active dependency; if so, progressively move responsibilities into focused utility modules while retaining compatibility re-exports.

## Recent Changes

### 2026-10-06 Release-audit closure

- [x] L3 truthful bounded-reporting blocker resolved by PR #201.
- [x] Accepted PR #201 head `62deba6a35d5d5f1d5c82f586d65bc8827e212ef`; CI #459 / `37399753801`; offline job `112064086574`; collect 24; full gate PASS / 100%; merge `91e39503c8e84d17752f9d26a23ff6b34db75b9e`; signature verified / valid.
- [x] PR #200 release-state declaration head `8d283b369da2989535c109fa4f046b2c7ba57f31` passed CI #463 / `37402351444`, offline job `112072129880`, collect 24 and full gate PASS / 100%.
- [ ] PR #200 final merge readiness still depends on fresh exact-head gate/review after the latest documentation corrections and explicit merge approval.

## Archived History

- `.codex/archive/backlog.md-20261006-134200.md` — complete pre-compaction backlog/history through PR #200 head `39177737486a372f38e9b6d81563d6f14327459a`. Historical unchecked K/L entries in that archive are superseded by the completed roadmap above.
