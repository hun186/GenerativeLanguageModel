# 待辦事項（Backlog）

## Current Summary

**Reduction Engine v1 = COMPLETE / RELEASE-READY.** A–L is complete, the L3 release-audit reporting blocker was resolved by PR #201, and the documentation/release closure was merged by PR #200. Authoritative Reduction v1 closure baseline: verified merge `99d79676b16b7fed54f9cf6e701441db79846cea`; later Hosted `main` includes the accepted GUI observability/layout fixes through `4a2eb27942d1bfda3ae845e877f5bac7d5df811c`.

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

## Issue #211 multistage JSON writeback corrective (2026-10-12)

- [ ] Review and land a narrowly scoped one-extract-stage `merge_slices: true` JSON stage writeback correction. Hosted main baseline is `c732991c8a1b612a0bcbd17c6c4db83e0a3bc0c8`; evidence: both Excel/SQLite example YAML configurations use `source: stage`, while the legacy stage artifact builder newline-joins individual JSON slices before Row Merger resolves them.
- New branch `fix/issue-211-single-extract-slice-writeback` validates each stage JSON slice, uses existing audited dict merge semantics only for one `extract` stage with explicit writeback and slice merge, keeps one-slice envelopes, and refuses invalid/partial inputs; unrelated real multistage output behavior remains unchanged.
- Focused tests cover both YAML configurations and actual stage-manifest to Row Merger resolution/flatten selection; Hosted `offline-e2e` must pass the new CI step and Codex must review exact head. No merge without explicit user authorization. Keep Issue #211 open until implementation is accepted.


### Future v1.1 candidates — not v1 blockers

- [x] Evaluate optional transient semantic/member caching only with a distinct authority/privacy contract; **decision: defer implementation until production evidence shows material duplicate member/semantic execution. No persistent second cache is allowed; SQL/ES persisted output and committed checkpoints retain their existing authority.**
- [x] Add a narrow task-specific final-result quality/coverage hook without creating a generic evaluation platform. Python-only `QualityHook` / `QualityAssessment` attaches safe scalar metrics/warning codes, may reject a final result explicitly, and contributes semantic hook metadata to the execution fingerprint.
- [x] Add narrow, read-only aggregate-lineage convenience APIs beyond the complete v1 `AggregateOutput` payload lineage contract (v1.1 PR pending Hosted exact-head CI and Codex review).
- [ ] Consider explicit maintenance/migration tooling for legacy unmarked stage artifacts; v1 GC intentionally never adopts them.
- [ ] Consider finer checkpoint coordination if production evidence justifies replacing conservative per-executable serialization.

### Existing technical-debt follow-up

- [ ] Evaluate whether `utils/utilities.py` remains an active dependency; if so, progressively move responsibilities into focused utility modules while retaining compatibility re-exports.

## Recent Changes

### 2026-10-06 v1.1 final quality/coverage hook

- [x] Added one optional Python-only final-result `QualityHook` on `ReductionStage`; no scorer registry, YAML schema, UI, or persistence layer.
- [x] Hook assessments expose only safe scalar metrics plus bounded warning codes; rejected results fail explicitly with `QualityCheckRejectedError`.
- [x] Hook semantic metadata participates in execution fingerprints only when a hook is configured, preserving no-hook fingerprint compatibility.
- [x] Extended the existing production ReductionStage E2E with real HTTP accepted/rejected quality-policy coverage; hosted acceptance is required before merge.

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

### 2026-10-12 execution order / GUI follow-up

- [x] GUI throughput/key-axis PR #209 merged to Hosted main as verified/valid `584a4345fe198544eb198eda9d99c2d948ee01d0` after exact-head `offline-e2e`, focused GUI regression and Codex clean review.
- [ ] Review and land the narrow v1.1 aggregate-lineage convenience API PR from `feat/reduction-v1-1-aggregate-lineage-helpers`; exact-head Hosted `offline-e2e` with focused tests and Codex clean required, user merge authorization required.
- Keep #203 transient semantic cache prototype **deferred** until production duplication/cost evidence or explicit user direction.

### 2026-10-13 Issue #211 physical E2E follow-up

- [ ] PR #213: accept exact-head Hosted offline E2E for SQLite+Excel two-slice JSON writeback and partial resume; complete Codex review and resolve all threads before requesting user merge authorization.
- [ ] Separately smoke-test with real external LLM and existing Windows / database deployment when available; offline model stubs and deterministic cut boundaries are not a substitute for production validation.

### 2026-10-14 PR #213 acceptance gate

- [ ] Confirm Hosted exact-head offline E2E and focused Issue #211 suite pass after durable A+B source/dispatch snapshot restoration, including SQLite/Excel task_key override, B-only resume, tampered-source refusal and verified nested retry descendants.
- [ ] Request and complete fresh Codex exact-head review, resolve all findings; report Windows self-hosted queue honestly. Await explicit user `merge` authorization.


### 2026-10-19 post-PR #216 ES production acceptance
- [ ] Validate proposed ES buffered-write acknowledgement PR at its exact head with Hosted offline E2E and fresh Codex review; do not merge without user authorization.
- [ ] Confirm locally deployed Windows executable commit includes merged #216 before touching real rows; stop/restart old process safely after in-flight work has drained.
- [ ] Controlled 1–3 item ES/Ollama acceptance including known date/importance failures, Event ID uniqueness, linked IDs, stored ES readback, pending/completion state, and immutable raw Success artifacts on rejection.
- [ ] Only after live acceptance, characterize bulk completion timing, pending failure counts and model token cost before resuming 37,286 candidate items. ES search refresh visibility and exact target index/key must be verified separately from bulk acknowledgement.


### 2026-10-20 Processing Quality follow-up / PR #218 acceptance
- [ ] Confirm exact-head offline-e2e and targeted quality tests, obtain fresh Codex review with no unresolved P1/P2, verify Windows self-hosted or disclose its queued state, and merge only on explicit user authorization.
- [ ] Add full single-slice worker/API failure taxonomy (transport, timeout, JSON generation, stage orchestration), expose retry/token cost and distinct affected-doc counts, and enable error drill-down with filters.
- [ ] Add rolling denominators, low-sample guardrails, optional anomaly thresholds, per-run export/history, retention/rotation with resumable aggregation, and Windows visual acceptance.
- [ ] Perform 1–3 controlled real ES/Ollama tests (pending and confirmed writes) before any 37k-row production replay.

### 2026-10-20 offline report PR follow-up (separate branch after merged #218)
- [x] Implement independent read-only report CLI for one run or bounded (max 100) run history: existing quality JSONL only, no raw doc IDs, no cross-run statistical mixing, optional atomic JSON report.
- [ ] Verify exact-head Hosted focused offline tests and formal Codex review on this PR, resolve findings; do not merge until explicit authorization and tomorrow's pinned #218 Windows acceptance remains unaffected.
- [ ] Continue taxonomy, filtering/drill-down, retention/rotation, and full Windows UI validation as separate stages; no LLM-dependent acceptance claims.

### 2026-10-22 Reduction v1.1 read-only legacy inventory (PR pending)
- [ ] Review bounded, count-only inventory for unmarked checkpoint/runtime directories under approved L3 item/prompt scopes; no file reads, migration, ownership adoption, or deletion.
- [ ] Verify Hosted exact-head Linux offline E2E plus focused new and L3 retention regressions, then obtain Codex review and address threads before requesting merge authorization.
- [ ] A future migration/GC adoption needs an entirely separate safety contract; checkpoint coordination requires evidence. #203 Semantic Cache remains deferred.

### 2026-10-22 LLM-call failure taxonomy P2 (separate PR pending)

- [ ] Add a strictly read-only per-run and bounded-history LLM **request** error breakdown from existing CSV, with conservative fixed codes (429/rate limit, timeout, transport, context budget, JSON post-processing, unknown), explicit denominator/low-n warning and **no exception text, URLs, tokens, prompts, document or path payloads exported**.
- [ ] Validate malformed/unbounded/in-progress CSV fail closed, no audit changes, and exact-head Hosted Linux offline CI plus Codex review. Keep stage-orchestration failures and document-level success outside this request-level measurement; no live LLM/ES claims.
- [ ] Subsequent phases, separately scoped: structured emission for non-LLM worker/stage failures, drill-down without sensitive data, JSONL lifecycle, real Windows visual acceptance.


### 2026-10-23 reconciled main and next Consumer-quality PR

- [x] Issue #211 fix #212 + SQLite/Excel offline E2E #213 merged and Hosted offline E2E verified; issue closed, real provider/Windows acceptance independent.
- [x] #219/#220/#221 merged; older unchecked “pending” sections above are historical rather than current PR state.
- [ ] Validate new Consumer orchestration event PR with exact-head Linux offline-e2e, focused `tests/test_processing_quality.py`, formal Codex P1/P2 review and zero unresolved threads; wait for user merge authorization.
- [ ] Independently instrument Stage Worker/Producer/Row Merger non-schema failures at authoritative event boundaries. Consumer incidents cannot be interpreted as whole-pipeline or document failure rate.
- [ ] Controlled 1–3 row Windows + Ollama + ES acceptance and independent ES readback before large batch replay. #203 transient semantic cache stays deferred.

### 2026-10-23 PR #222 accepted; next Row Merger retry incident PR

- [x] Consumer run-scoped orchestration event PR #222 merged into `main` as `bd3fc22c647ef296c2210750a69c78c168c50904` after clean formal Codex exact-head re-review, zero unresolved threads, and Linux offline E2E. The post-merge Linux offline-e2e passed; Windows self-hosted queue explicitly skipped for now by operator request.
- [ ] New independent P2 PR: Row Merger **non-schema retry** incident telemetry at its actual retry handler, throttled by the existing log window. Two run-scoped codes (prepare/writeback), never raw IDs/messages; added to Processing Quality GUI and offline per-run snapshot. Does not redefine document success/failure or change retries.
- [ ] Obtain latest exact-head Hosted Linux offline-e2e (including `tests/sql_mode/runtime/test_row_merger_schema_failure.py` and `tests/test_processing_quality.py`), formal Codex review with zero unresolved findings, then require explicit user merge authorization.
- [ ] Subsequent separate scopes: Producer / Stage Worker durable operational exception taxonomy, bounded filter/drill-down and JSONL retention; no real Windows/ES/Ollama acceptance claim before operator can deploy and verify.

### 2026-10-23 PR #223 closure and independent Producer quality follow-up

- [x] PR #223 merged `a9240f826bfef9a999848017a254c69c5c05f748` after exact-head Linux offline E2E, formal Codex no-findings and all threads resolved; do not equate earlier unchecked PR #223 rows with current state.
- [ ] New P2 Producer operational incident telemetry: non-Schema schedule/backpressure/future catch sites, no raw IDs or exception text; require exact-head Hosted Linux offline E2E including focused Producer tests, Codex clean review, and explicit merge authorization.
- [ ] Stage Worker non-LLM exceptions and structured per-stage/worker taxonomy as a separate PR; require source-authoritative boundaries, cancellation exclusion and payload-free audit. Neither Producer nor Row Merger event counts are a document failure rate.
- [ ] Retention/rotation with resumable aggregation, bounded drill-down/filters, and 1–3 real Windows/Ollama/Elasticsearch writeback/readback acceptance when operator environment is ready; Windows self-hosted runners deliberately deferred.
