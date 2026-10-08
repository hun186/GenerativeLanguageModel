# Project Memory

## Current Summary

- This Python project processes TXT/Table/SQL/ES inputs through prompt, multistage, reduction, and writeback infrastructure.
- **Reduction Engine v1 is COMPLETE / RELEASE-READY.** A–L is complete; PR #202 documentation/cache-boundary evaluation and PR #204 task-specific quality hook are merged. Current Hosted `main` for this GUI work is verified merge `358a0b17a55fa38c4ed074e6245776a4624860ce`.
- PR #201 authoritative runtime evidence: accepted head `62deba6a35d5d5f1d5c82f586d65bc8827e212ef`; CI #459 / `37399753801`; offline job `112064086574`; collect 24; full gate PASS / 100%; merge `91e39503c8e84d17752f9d26a23ff6b34db75b9e`; signature verified / valid. PR #200 final accepted head `36a40eb37827e33545865203b079aefaab1ba1f4` passed CI #467 / `37420475520`, offline job `112128483703`, collect 24 and full gate PASS / 100%; zero unresolved review threads; fresh Codex review reported no major issues; merge `99d79676b16b7fed54f9cf6e701441db79846cea` is verified / valid.
- L2a authoritative evidence: PR #195, accepted head `f4ad4001f4498287799df3c89e90ff4a733dc572`, CI #448 / `37179982321`, offline job `111370415206`, collect 22 and full PASS, merge `c1f2f6974e88028eb3eb5b9b747fefeb8d6d5cf0`, verified/valid signature. PR #194 is closed/unmerged/superseded.
- Production operator cancellation is cooperative and distinct from worker teardown. It stops new scheduling and semantic continuation while allowing in-flight external calls and existing consumer/merger/writeback work to drain.
- Production Reduction observability uses allowlisted bounded JSONL, lock-protected counters, and a separate Windows GUI Reduction Status panel. Current GUI work adds a third default-collapsed LLM Token / Context Distribution panel backed by per-run `llm_call_audit`.
- Required dependency installation remains blocked by the pinned GitHub `peft` clone proxy 403. Dependency-light tests are locally available; hosted offline E2E is authoritative.

## Recent Changes

### 2026-10-08 Windows GUI LLM token/context distributions

- Started from verified Hosted `main@358a0b17a55fa38c4ed074e6245776a4624860ce` after PR #204 merged.
- Extended `llm_call_audit` with local `task_text_tokens`, `template_tokens`, `rendered_prompt_tokens` and a source marker. API-reported input/output/total/context usage remains authoritative; local prompt-component counts are explicitly observability estimates.
- Prompt generation writes numeric-only component metadata outside TODO/RUNNING so queue claim/requeue cannot dispatch metadata as prompt work. Streaming workers read that metadata after TODO→RUNNING claim without depending on the original queue location.
- Windows GUI receives only the run audit path, polls the append-only CSV when it changes, and exposes a default-collapsed `LLM Token / Context Distribution` panel with Input, Output, Template, Task text, Context %, and prompt-backed Slice latency curves plus P50/P95/max summaries.
- Calls without API usage are excluded from API token/context distributions instead of appearing as synthetic zero-token calls; component coverage is shown separately. Direct calls without `prompt_file` (for example JSON repair) are excluded only from Slice latency so that chart remains a literal per-slice distribution.
- Fresh Codex review on the first PR #207 head found a P2: multi-stage prompt replacement could reuse the initial sidecar. The corrective centralizes metric refresh, clears stale metadata before recounting, and refreshes metadata against every actually rendered stage prompt basename.
- Fresh Codex review on the subsequent exact head found a second P2 in the collapsed summary: absent API usage could display as `In/Out P50 0`. The corrective now checks sample counts and renders `In unknown` / `Out unknown`, matching the distribution loader's no-synthetic-zero contract; regression coverage locks the outage/no-usage case.
- Fresh Codex review on `54d718e68d0b52677f8fb23a37692bfb81eecf0f` found a third P2: full growing-CSV rescans and percentile sorting were running on the Tk event loop. The corrective moves audit parsing/calculation to a daemon reader thread and sends only completed snapshots back to Tk; regression coverage requires `_gui_proc_main` not to call `load_llm_audit_distribution()` directly and verifies loader execution on the worker thread.
- Fresh Codex review on `626ff97741a1231d23281e31637ff3a87de4daaf` found a fourth P2: local rendered/template token counts could miss the runtime Qwen `/no_think` suffix added at dispatch. `finalize_llm_user_content()` is now the shared request-finalization boundary used by both `CallLLMAPI()` and prompt-component counting; regressions verify the runtime suffix is included.
- Fresh Codex review on `538de5c906fb7d800ad667b3cafe34f0b143e20d` found a fifth P2: expanded charts still rendered empty metric percentiles as zero. The corrective now checks `count` and renders `P50/P95/max unknown` for empty series, matching the collapsed summary's unavailable-data semantics.
- Fresh Codex review on `f1da49273394185661597641a6f77f29278b5843` found a sixth P2: one successful LLM request followed by local post-processing/persistence failure could emit both success and failure audit rows. `PromptAPIPipeline.proc()` now defers auditing until the final outcome and emits at most one row per attempted request, retaining API response usage/latency when a later local step fails.
- Focused local clone/test execution is unavailable in this environment because GitHub DNS cannot resolve; fresh Hosted CI and Codex review are required before merge readiness.

### 2026-10-08 PR #204 merged

- Accepted exact head `48bcf602a527a28db5d6aba1fadf109136d74711` passed authoritative CI #511 / `37606218508`, offline job `112742220163`, collected 25 E2E cases and full gate PASS / 100%; fresh Codex review reported no major issues and unresolved threads were zero.
- PR #204 merged as verified/valid `358a0b17a55fa38c4ed074e6245776a4624860ce`.

### 2026-10-07 PR #204 current-main reconciliation

- Retargeted the task-specific Reduction quality-hook PR from the historical PR #202 stack onto current Hosted `main@43d9c43349a6b3309993ecb8ddb684cc0e36ecd9`.
- Replayed only the quality-hook implementation/docs/tests onto the current main tree so later GUI observability/layout and PR #202 documentation corrections are preserved.
- Historical acceptance on the old stacked head is non-authoritative after reconciliation; fresh exact-head hosted `offline-e2e` and Codex review are required before merge readiness.

### 2026-10-07 PR #202 current-main reconciliation corrective

- Fresh Codex review of reconciliation head `345c8263052239e8a4d08b03aa377a554897869a` found that the v1 guide had lost current-main GUI observability guidance while replaying the cache-evaluation documentation.
- Restored the accepted collapsible Recheck/Reduction sections, always-visible Reduction Cancel control, and mode-aware `ReductionStage` / legacy `merge_slices` / inactive explanations without changing runtime behavior.
- The pre-corrective head's hosted `offline-e2e` success is historical evidence only; this corrective requires a new exact-head hosted gate and Codex review before merge readiness.

### 2026-10-07 Windows GUI status panels side-by-side

- Recheck Status and Reduction Status now share one equal-width horizontal status row instead of consuming separate vertical rows; both retain independent collapse/expand behavior, and Reduction keeps its always-visible Cancel control.
- The change is layout-only: Recheck/Reduction data flow, counters, error presentation, cancellation semantics and observer contracts are unchanged.
- Added a source-level GUI regression that requires one shared parent row, equal-weight columns, left/right grid placement, a right-side Reduction control container packed before the expandable summary so Cancel remains visible under the default window width / Windows DPI scaling, and responsive detail-label wrapping derived from the shared row width so expanded diagnostics remain readable at half width. Hosted exact-head acceptance and fresh Codex review are pending for this branch.

### 2026-10-06 Windows GUI live observability / compact status fix

- Fixed Recheck GUI freshness for slow SQL/ES jobs: the first dispatch recheck publishes immediately, then updates on either the existing count threshold or a default 1-second time threshold, with final forced delivery. Run-scoped locking serializes cumulative stats plus time-based GUI publication under multistage row parallelism so snapshots cannot regress or defeat the throttle; GUI queue failures are swallowed locally and cannot alter pending decisions or scheduling.
- Made Reduction GUI mode-aware. Legacy slice-merge activation and the post-drain fallback gate both use the same canonical `should_merge_slices()` predicate as execution (including `merge_slices`, `enable_slice_merge`, and supported `merge_strategy` aliases), then reports dedicated merge attempt/completion/failure counters from the actual row-merger combine path (with the fallback sweep still covered) instead of misleading Stage/Member 0/0 values; observer activity-mode transitions force-publish to the GUI. Orchestrator fallback merge success is conditional on publishing the actual combined artifact path back to any still-live registry row, preventing suffix/path mismatches from leaving a completed-but-undiscoverable claim that stalls Row Merger. A live registry row whose existing `CombBackFN` points to a real artifact is authoritative: fallback skips it and the registry handoff layer refuses to overwrite it, preserving multistage scheduler output while slow sink/writeback drains. Row Merger treats artifact materialization and semantic slice merge as distinct phases: fallback ownership transitions through a shared `materialized` handoff state before publishing `CombBackFN`, Row Merger atomically adopts that state without double-counting the started event, and legacy completion is emitted only after the actual `list[dict]` merge succeeds or a premerged dict is confirmed; merge/parse/handoff/unsupported-payload outcomes emit failure and release the shared claim, including fallback-only materialized artifacts that Row Merger cannot semantically merge. If the registry row disappears during fallback because another path already completed writeback, orchestrator releases the materialized ownership and closes the fallback attempt as superseded instead of leaving a permanent Merged 0/1 state. Legacy telemetry is gated on the real merge_slices switch, row-merger/fallback share one run-scoped claim so the same item cannot be merged or counted twice, failed claims are released for retry, and premerged multistage `CombBackFN` dict outputs are explicitly accounted when Row Merger confirms the combined-source writeback.
- Recheck Status and Reduction Status are collapsible by default with one-line header summaries. The Reduction Cancel control remains visible while collapsed. Reduction snapshot capture plus GUI queue submission is serialized by a dedicated publish lock so concurrent forced stage-start snapshots cannot arrive out of order while counter mutation remains independently lock-protected.
- Regression coverage locks the first/time-based recheck snapshots, legacy merge observer counters, mode-aware formatting, and collapsible source contract.

### 2026-10-06 v1.1 final quality/coverage hook

- Added `czjLLM/reduction/quality.py` with a narrow `QualityHook`, immutable payload-free `QualityAssessment`, and explicit quality error/rejection types.
- `ReductionStage` now optionally evaluates exactly one caller-supplied hook after the final single-pass or hierarchical result. Accepted scalar metrics are nested under `metrics["quality"]`; audit records only acceptance, hook contract version, metric names and warning count. Rejection fails closed without putting payload text in the exception.
- A configured hook's contract/version + safe semantic metadata participates in the stage execution fingerprint. With no hook configured, the fingerprint metadata shape remains unchanged.
- No generic scorer registry, root YAML/config surface, model judge, UI, or persistent quality store was added.
- Verification added to `tests/e2e/test_reduction_stage_e2e.py`: real HTTP quality-hook acceptance and rejection, fingerprint distinction, payload-free rejection, and execution-budget release. Hosted offline E2E acceptance is required on the PR exact head.

### 2026-10-06 v1.1 transient-cache evaluation

- Evaluated optional transient semantic/member caching after the v1 closure. Existing authorities already cover distinct retry scopes: persisted SQL/ES destination output is cross-run reuse authority and committed hierarchical checkpoints are resume authority.
- No production evidence currently establishes enough duplicate same-semantics member/semantic execution within one run to justify a new cache, while disk/global caching would add a second result authority and a new source-derived data retention/privacy surface.
- Decision: defer implementation. Reopen only with measured duplicate-call/cost evidence. Any future design must be opt-in, bounded, run-scoped, non-persistent by default, cache successful results only, remain outside semantic identity/authority, preserve cancellation/failure/observer semantics, and never persist source/prompt/output payloads merely to obtain cache hits.
- Verification basis for this evaluation: source/contract review of `czjLLM/reduction/stage.py`, `czjLLM/reduction/execution.py`, `czjLLM/reduction/persisted_freshness.py`, `czjLLM/reduction/runtime_semantic.py`, `czjLLM/reduction/reducers/semantic.py`, `tests/reduction/test_semantic_runtime.py`, `tests/reduction/test_semantic_reducer.py`, `tests/reduction/test_reduction_processing_identity_l1.py`, and the v1 operator guide. No production Python behavior changed.

### 2026-10-06 PR #200 merged closure

- Final accepted PR #200 head `36a40eb37827e33545865203b079aefaab1ba1f4` passed CI #467 / `37420475520`, offline job `112128483703`, collect 24 and full production E2E PASS / 100%.
- Fresh Codex review on that exact head reported no major issues and unresolved review-thread count was zero.
- PR #200 merged as verified/valid `99d79676b16b7fed54f9cf6e701441db79846cea`; this is the authoritative Reduction Engine v1 closure baseline.

### 2026-10-06 Active project-memory compaction

- Compacted `.codex/architecture.md`, `.codex/api_contract.md`, `.codex/known_issues.md`, `.codex/decisions.md`, and `.codex/backlog.md` because each exceeded the AGENTS.md threshold of 20 dated/work blocks.
- Preserved each complete pre-compaction file first under `.codex/archive/*-20261006-134200.md`, then rewrote active files to current summaries, recent relevant changes, and archive references.
- Preserved unresolved issues, open backlog items, current API contracts and still-effective architecture decisions. Superseded point-in-time PR status remains available in the archives.
- Verification passed on compaction head `a795e8c2a632ebe4a329b27c489a1723820ca85a`: each new archive blob SHA exactly equals its pre-compaction source blob SHA (`architecture` `2575101c…`, `api_contract` `6df215ab…`, `known_issues` `07e77c6c…`, `decisions` `5674d347…`, `backlog` `8f549cf8…`). Active heading/work-block counts are architecture 8, api_contract 15, known_issues 10, decisions 7, and backlog 8, all below the >20-block compaction trigger. The follow-up evidence-only head `36a40eb37827e33545865203b079aefaab1ba1f4` subsequently received fresh hosted 24-case acceptance and fresh Codex review, then merged through PR #200.


### 2026-10-06 PR #200 fresh closure acceptance

- Initial documentation reconciliation head `06f0c6b0a6443999a7241b6e5cce0736cde71d38` passed CI #462 / `37401880432`, offline job `112070871594`, collect 24 and full gate PASS / 100%.
- The release-state declaration was then recorded on head `8d283b369da2989535c109fa4f046b2c7ba57f31`; that exact head independently passed CI #463 / `37402351444`, offline job `112072129880`, collect 24 and full production E2E PASS / 100%.
- Reduction Engine v1 was recorded as COMPLETE / RELEASE-READY. The later review/documentation corrections were accepted on exact head `36a40eb37827e33545865203b079aefaab1ba1f4` and merged through PR #200.

### 2026-10-06 L3 release-audit corrective accepted

- PR #201 corrected truthful bounded-retention reporting with the run-local `deletion_budget_exhausted` latch: after deletion budget exhaustion, validation/classification/counters continue and deletion stays disabled for the rest of the sweep.
- Deterministic regressions cover a later malformed tombstone and the case where a large artifact exhausts the byte budget before a smaller candidate. Hosted acceptance: head `62deba6a35d5d5f1d5c82f586d65bc8827e212ef`, CI #459 / `37399753801`, offline job `112064086574`, collect 24, full gate PASS / 100%.
- PR #201 merged as verified/valid `91e39503c8e84d17752f9d26a23ff6b34db75b9e`. The remaining documentation closure subsequently passed its fresh exact-head gate/review and merged through PR #200 as `99d79676b16b7fed54f9cf6e701441db79846cea`.

### 2026-10-05 Reduction Engine v1 closure audit

- Audited production contracts and tests for configuration/reducers, hierarchical checkpoints, execution budget, collection/aggregate adapters, nested execution, persisted freshness, partial success, cancellation, observability, and retention. No production Python behavior was changed.
- The audit found one release-readiness blocker: bounded GC breaks candidate traversal at its deletion budget, so a later invalid tombstone is scanned but omitted from `skipped_invalid`; the focused L3 regression fails on Python 3.14. A separate runtime corrective and fresh hosted gate are required before this closure may declare v1 release-ready.
- Added the consolidated source-backed operator/developer guide and reconciled the implementation roadmap to A–L complete while keeping closure/release readiness explicitly blocked. Historical pending implementation claims below are superseded point-in-time records.
- Canonical evidence (all merge signatures verified/valid): L1 PR #193, head `874ef7f8790d38c9c958dfdba0e5d020662da7eb`, CI #443 / `37120493902`, job `111195487211`, collect 21, merge `21038d2678290cd32730009f552809730722aab4`; L2a PR #195, head `f4ad4001f4498287799df3c89e90ff4a733dc572`, CI #448 / `37179982321`, job `111370415206`, collect 22, merge `c1f2f6974e88028eb3eb5b9b747fefeb8d6d5cf0`; L2b PR #197, head `b0a14e2c855a28d7d44efe9edcfd587fd689e9c8`, CI #451 / `37186996174`, job `111390932764`, collect 23, merge `47488c807924fafe71c4d53d1c2999bc4675464f`; L3 PR #199, head `ffccffe4d8d93a0e74bbc631ab3736c2d153b0d6`, CI #454 / `37210792470`, job `111461389202`, collect 24, merge `fe93663dc06909652fb2c4bec32e98cbd8520989`. Each full offline gate passed.
- Replacement history: #194→#195, #196→#197, and #198→#199; replaced PRs are historical, closed, unmerged, and superseded.
- Verification: dependency installation remains blocked by the pinned `peft` GitHub proxy 403. The focused config/stage/nesting parser suite passed (118 tests); the required full `tests/reduction` command stopped at the L3 reporting failure described above; all other Reduction tests passed when that single blocker regression was isolated. Compileall and `git diff --check` passed (compileall emitted one pre-existing invalid-escape SyntaxWarning in `job_manager/console_ui.py`).

### 2026-10-04 PR L2b implementation

- Added root production cancellation helpers, canonical production ExecutionContext construction, immutable operational tags, generic observer contract/default, bounded production JSONL observer, and thread-safe snapshots.
- Bridged cancellation through SQL/Table/ES producer orchestration, pending-running release, single/multistage calls, combine reduction, hierarchical callbacks, and both production runtime adapters.
- Added GUI process-safe Cancel IPC and fixed Reduction Status panel while retaining Recheck Status and window-close semantics.
- Added focused production-control/privacy/fingerprint and GUI snapshot tests. Complete Reduction suite passed locally. SQL runtime collection is locally blocked at missing `tqdm` after the required dependency install failed through the known proxy restriction.

### 2026-10-04 PR L2a accepted baseline

- PR #195 supplied partial success and cooperative cancellation core; 22 hosted E2E cases passed and merge `c1f2f6974e88028eb3eb5b9b747fefeb8d6d5cf0` is the exact L2b baseline.
- Only `ExecutionError` is recoverable member failure. Cancellation and programmer/system faults propagate; manifests and aggregate identity remain unchanged.

### 2026-10-03 PR L1 accepted baseline

- Persisted SQL/ES outputs remain reuse authority; semantic executable fingerprints govern freshness and pending recheck has its own bounded event stream and fixed GUI panel.

## Archived History

- `.codex/archive/memory.md-20261004-060113.md` — compacted 2026-10-04; contains the complete pre-L2b project-memory history through L2a. Compaction was triggered because active memory exceeded 40 KiB. Verified by preserving this archive before rewriting active memory.

### 2026-10-04 L2b local verification

- Required setup: `python -m pip install --upgrade pip` could not reach the configured package index through the proxy; `python -m pip install -r requirements.txt` failed cloning pinned GitHub `peft` with HTTP 403.
- Passed: focused L2b production-control/GUI plus L2a selection (26 tests), complete `tests/reduction`, GUI/recheck selection (4 tests), prompt-pipeline regression selection (16 tests), compileall, and `git diff --check`.
- Environment-limited: SQL runtime collection stops on missing `tqdm`; the new localhost E2E reaches the same missing dependency before HTTP dispatch. Hosted CI must perform the authoritative 23-case collection/full gate.

### 2026-10-04 PR #196 production-boundary corrective

- Corrected synchronous multistage cancellation propagation/registry cleanup, deterministic combine safe drain, Row Merger cancellation no-spin cleanup, manual merge suppression, and terminal cancellation classification.
- Added throttled live/final GUI observer snapshots with final-before-close ordering and counter-only attempted/succeeded events so failed, rejected, cancelled, and fatal stages retain truthful cumulative work counts without per-success JSONL volume.
- Strengthened the sole L2b E2E to call real SQL `run_pipeline()`/producer/scheduler/shutdown with localhost HTTP cancellation and a deterministic writeback safe-drain phase; hosted count remains 23.
- Local verification so far: focused Reduction/GUI/scheduler/producer selection and complete Reduction suite passed; prompt regressions and explicit L2a regressions passed. Required dependency install remains proxy-blocked, so hosted execution is required for SQL/Row Merger and production E2E proof.

### 2026-10-04 PR #196 corrective verification

- Passed locally: complete Reduction suite; focused scheduler/producer cancellation selection; GUI/recheck selection; prompt-pipeline selection; explicit L2a suite; compileall; and diff check.
- Environment-limited: full SQL runtime suite stops during collection because `tqdm` is unavailable, and the strengthened production L2b E2E stops during collection because PyYAML is unavailable. Both are consequences of the required requirements install failing on the proxy-blocked pinned `peft` clone and require fresh hosted CI.

- Publication check: `git push` could not run because this checkout has no configured push destination. Corrective commit is local; fresh hosted head/CI evidence is unavailable and PR #196 remains unmerged.

### 2026-10-04 PR L3 retention / safe GC implementation

- Started from exact verified L2b merge `47488c807924fafe71c4d53d1c2999bc4675464f`; canonical L2b evidence is PR #197, accepted head `b0a14e2c855a28d7d44efe9edcfd587fd689e9c8`, CI #451 / `37186996174`, offline job `111390932764`, collect 23/full PASS. PR #196 is closed/unmerged/superseded.
- Added strict disabled-by-default operational retention policy, bounded ownership markers, cross-process expiring execution leases, race-safe GC claims/tombstone deletion, checkpoint-chain validation, containment/symlink protection, dry-run, budgets, summaries, transient success cleanup and post-writeback production sweep.
- Authoritative persisted results/manifests/aggregate identity/final outputs and legacy stage artifacts remain excluded; no second member-result cache exists.
- Local verification: focused retention tests, complete Reduction suite, and the sole new L3 E2E pass. Required dependency installation and GitHub access remain proxy-blocked; hosted 24-case acceptance is pending.
- Verification details: complete `tests/reduction` passed (401 tests); focused retention plus L3 E2E passed (9 tests); explicit L1/L2 regression selection passed (30 tests); prompt-pipeline regression selection passed (16 tests); compileall and diff check passed. SQL runtime and legacy checkpoint E2E collection are environment-limited by unavailable `tqdm`/`opencc` after the pinned dependency install failed. Full hosted collect-only/24-case execution remains pending.

### 2026-10-04 PR #198 corrective

- Pre-corrective hosted head `2071e80857b7184593002807b7a18eba76485204`, CI #453 / `37190651752`, offline job `111401921897`, collect 24/full PASS is pre-corrective evidence only.
- Corrected canonical root YAML projection, explicit one-level prompt-container discovery for unscheduled historical items, and exact/budgeted/reported crash-tombstone recovery. Added pre-L3 no-adoption, active/claim/stale-young lease, config/fingerprint, historical-item, symlink, and tombstone budget regressions while retaining one L3 E2E.
- Local corrective verification: focused L3 12 passed; complete Reduction 405 passed; checkpoint/nested 59 passed; L1/L2 30 passed; prompt pipeline 16 passed; strengthened single L3 E2E passed. SQL runtime collection remains environment-limited by missing `tqdm` after the known proxy-blocked dependency install.
