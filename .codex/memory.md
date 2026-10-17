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

### 2026-10-08 GUI distribution hover help

- Added `ⓘ` hover help for the Windows LLM Token / Context Distribution panel.
- Header hover explains that the curves are normalized histogram outlines rather than time series; per-metric hover explains Input, Output, Template, Task text, Context %, and Slice latency semantics plus n/P50/P95/max.
- Small-sample guidance explicitly warns operators to prioritize percentiles over curve shape; no prompt/output payload is exposed.

- Follow-up UX refinement: Template no longer occupies a histogram panel because YAML stage templates are typically fixed or near-fixed. The collapsed header now shows Template P50/P95; the former Template panel is Slice time, and the second row expands Task text / Context % across two columns. "Slice latency" was renamed "Slice time（切片耗時）" and explicitly means request-to-response elapsed time only, excluding queue, post-processing, merge/reduction, and output writes.

### 2026-10-12 GUI throughput / axis follow-up (PR pending)

- From verified Hosted main `6a7448a83bbf236bc4227c7f474c6b3fca4b53ec` (PR #208 merged), started `feat/gui-audit-throughput-axis-v1`. The only current open PRs at branch start were #203 (deferred), #160 and #34; there was no later open GUI PR.
- Historical `processing_tps` is API `total_tokens / elapsed` and has zero-time fallback. Leave its field semantics unchanged. The GUI derives exact requested Total tok/s from API input+output over positive per-slice elapsed instead.
- Provider cached prompt-token usage now has an explicit nullable audit field plus provenance, accepting explicitly reported zero. Only where absent, group by model/endpoint/task/stage and local token source, require two prior stable template-size samples (5% tolerance) and discount the presumed stable template floor by 50%. This is an explicitly uncertain heuristic, not proof of reused token prefix or provider cache hit.
- Numeric local sidecars hold only token counts plus safe stage label; single-stage identity is the literal `single_stage`, not a task prompt. GUI reads CSV metadata only and plots 3+4 distribution charts with comma-grouped key x labels.
- Scope closes at GUI improvement. Once review clean and exact-head offline-e2e passes, await explicit merge instruction; next authorized v1.1 work is narrow AggregateOutput lineage convenience APIs, not #203 cache prototype.

- PR #209 exact-head Codex follow-up: the original decimal-safe display helper was bypassed by the collapsed Context % and Slice time summary; both now use `_fmt_audit_number` consistently, preserving `%`/`s` units, comma grouping, and unknown-count semantics. Added behavioral summary regression at `2.25 -> 2.3`, including real CSV percentile ingestion and float-artifact P95 `67.74999999999999 -> 67.8`. Exact-head Hosted `offline-e2e` and fresh Codex review are required again; do not merge without user authorization.

### 2026-10-13 Issue #211 SQLite/Excel offline E2E follow-up (PR #213; pending acceptance)

- Merged PR #212 (`20113bebecdc267e8a4e3f5473444076437c295c`) previously verified slice JSON merging with focused tests, but its dedicated tests did not run physical SQL/Excel full-stage writeback with a fake HTTP model.
- Added `tests/e2e/test_issue_211_sqlite_excel_writeback_e2e.py`: two source slices with deterministic token boundaries, real prompt production/stream scheduler/extract processing, localhost fake OpenAI JSON replies, real SQLite/Excel sinks and persisted row readback. Added a separate interruption/resume test seeding one hash-verified Success sibling plus one TODO sibling, then running the actual single-extract controller and physical sinks.
- First Hosted run `38404227737` exposed incomplete stage execution in the SQL acceptance; initial fixture was improperly retaining successful TODO. Corrected fixture to use production success cleanup. E2E also exposed a separate scoped first-extract-stage data-loss risk where full-row source re-rendering replaced distinct already-generated primary-input slice prompts; proposed a narrowly scoped preservation fix in `pipeline_controller.py` on PR #213.
- **Verification remains pending** for the latest exact PR head; do not equate previous CI successes or simulated model replies with a live external-model acceptance. No merge without explicit user direction.

### 2026-10-14 PR #213 partial-resume source provenance corrective (pending hosted validation)

- Codex found P1 at old PR head `1ae2c8e`: when an extract task uses `task_key` differing from the initial fallback task, a partial resume may contain only unfinished B in root TODO, making the prior raw-snapshot creation reject or overwrite an intact A+B snapshot.
- Added a durable `_stage_outputs/original/_source_slice_provenance.json`: source SHA-256, ordered original filenames, per-piece SHA-256, actual per-slice dispatch SHA-256, and effective stage-task identity. On resume, independently retokenize the current source and validate saved raw snapshots; accept a reduced TODO subset and verified queued retry descendants, never promote copied prompt text to trusted raw source.
- Single extract final Success-coverage now includes completed original members from the verified manifest; it does not drop previously successful A when only B remains queued. Stage/task changes or modified source fail closed rather than silently combine stale results. Nested split children retain their verified queued prompt identity.
- Added physical SQLite/Excel interruption-resume and stale-source rejection E2E with localhost fake OpenAI; first attempt is intentionally interrupted after the real stage prepares prompt provenance, then A is completed, leaving only B to dispatch on restart.
- Validation of latest exact head remains pending. Linux CI for prior `1ae2c8e` passed, but does not validate this corrective. Keep PR #213 OPEN and request fresh Codex review before any merge authorization.

### 2026-10-14 PR #213 smart-reset provenance fix (pending exact-head acceptance)

- Codex's new P1 on `a42c5ff` identified that `smart_reset` deletes `_stage_outputs`, including the earlier raw-source provenance manifest, before a B-only resumed input can restore completed A coverage.
- Moved the SHA-256-only manifest to `_extract_slice_identity/source/original.json` (outside resettable stage snapshots). On explicit `smart_reset`, retokenize current original source and verify its full hash, ordered per-slice hashes and durable identity before reconstructing missing transient raw-source snapshots. On ordinary `resume`, missing/corrupt snapshots fail closed instead of being silently replaced. On legacy partial Success with no durable manifest, reject incomplete source-to-TODO mapping rather than dropping A.
- Added parameterized SQLite and Excel E2E for `resume` and `smart_reset`, each both happy-path Success-A/TODO-B and changed-source refusal. PR remains OPEN pending new exact-head CI and Codex; do not merge without user authorization.

### 2026-10-14 PR #213 callable task identity + multistage isolation (pending acceptance)

- Latest Codex review on `655bf93` completed with two P1s: `stage_task_sha256=digest_text(str(stage_defs[0].task))` was unstable for callable templates whose repr includes process-specific addresses, and non-single-extract multistage restarts incorrectly honored an Issue #211-only source manifest even with changed source and fresh TODO.
- Introduced `czjLLM/prompt_pipeline/task_fingerprint.py`: stable canonical source/function/defaults/closure and structured fields, never callable memory addresses; dynamic unsupported objects fail closed. Both extract dispatch-record and resume checking now use `fingerprint_task`.
- Ordinary multistage runs explicitly bypass Issue #211 durable raw-source-provenance enforcement and rebuild/fallback to current snapshots with no stale marker veto. Added E2E with stale single-extract manifest and changed ordinary multistage inputs for `resume`, `smart_reset`, and `full_restart`; added callable identity stability/change tests.
- This is an **unmerged PR #213 change pending exact-head Linux CI and fresh Codex Review**, not a completed main capability. No merge without user authorization.

### 2026-10-14 PR #213 latest Codex P1 corrections (not merged; exact-head CI pending)
- Previous review on `f41e0ed` finished and identified two P1s: task fingerprint could collapse two different same-line lambdas when inspect.getsource returns the same assignment text, and retry could overwrite a saved `dispatch_sha256` for queued B despite earlier recorded B identity while A was already Success.
- `task_fingerprint.py` now **always** includes function bytecode/constants/freevars even when source is available. Regression: same-line lambdas with identical qualname/source but different literal constants must hash differently.
- `pipeline_controller.py` now checks all existing queued prompt SHA-256 values against persisted dispatch SHA-256 *before* modifying expected membership or committing any updated manifest; mismatch fails closed instead of mixing old Success A with changed B. Full restart, which deliberately invalidates old lineage, is handled separately. Parameterized SQLite/Excel `resume`/`smart_reset` integration cases inject changed B rendering with A in Success, assert zero new external-model requests and unchanged durable dispatch manifest.
- Exact-head CI and fresh Codex review remain outstanding; user has NOT approved a merge.


### 2026-10-14 PR #213 referenced-global semantic fingerprint P1 (pending review)
- Initial P1 on 7be1881: only global symbol names were recorded, so changes to module prompt rules, flags and helpers could incorrectly preserve Success.
- Current fix fingerprints only global names that code actually loads (including nested code), their values and transitive helper functions, with recursion guards and stable builtin identities. Unsupported/unbound dynamic dependencies fail closed. Raw rule text and prompts are never written to provenance; hashing does not execute templates.
- Added SQLite/Excel real-controller A-success/B-TODO and all-Success global-change rejection coverage, plus unit regressions for global string/flag/helper changes, nested loads, cycles and separate Python processes. Existing sink readback, smart_reset, full_restart, and normal multistage checks remain in the test file.
- Implementation commit 6047981 and regression commit b7dc84d. New exact-head Hosted CI and Codex review remain to be accepted. Previous Windows self-hosted jobs remained queued. Do not merge without user authorization.


### 2026-10-14 PR #213 second Codex round / 2 P1 + 1 P2 (pending new CI)
- Fresh Codex review of 6a88d44 reported P1 all-Success reuse missing renderer context, P1 callable parameter ABI omissions, and P2 dynamic globals()/eval() namespace access.
- Correctives: pipeline_controller now fingerprints effective task + keyConsiderations, think_mode, main_file_name, initial task in both dispatch and resume validation; task_fingerprint hashes varnames, argument counts, flags, cellvars and exception table; globals/locals/vars/eval/exec/__import__ namespace lookups explicitly fail closed.
- Expanded real-controller SQLite/Excel acceptance verifies all-Success context drift rejection with no stale LLM calls, while same-line callable parameter changes and dynamic-lookup attempts are regression tested.
- Corrective commits 9c9c22b (ABI/dynamic), d7846ba (renderer context), f546c12 (tests). Previous exact-head 6a88d44 Linux offline-e2e SUCCESS, but NEW exact-head Hosted CI and fresh Codex review still required. No merge without user authorization.


### 2026-10-14 PR #213 third Codex round / task-setting aliases and callable state (pending CI)
- Exact-head d48011a Codex found P1 missing transitive ctx.taskSetting alias target identity and P2 missing mutable function attributes (function self-reference case).
- Controller now mirrors actual renderer task pool precedence and resolves only reachable task mappings/aliases, including fallback global task entries. Circular alias references fail closed, without executing templates or hashing the entire task pool.
- Fingerprint includes function/partial custom __dict__ attributes; self-reference is recursion-guarded and changing template.prefix changes the hash.
- Added real-controller SQLite/Excel acceptance for all-Success alias target and callable attribute drift with zero provider calls and unchanged stored Success; unit tests cover transitive chains and cyclic aliases.
- Corrective commits ea9715b (callable attrs), a8901d9 (task alias resolution), b2665a6 (regressions). Prior exact-head d48011a E2E gate SUCCESS, but new exact-head CI and Codex review are still unaccepted. Do not merge without authorization.

### 2026-10-15 PR #213 fourth exact-head Codex / runtime finalization and slotted bound methods
- Codex review of exact head 397ee7a7 completed and raised P1: model_spec.model_name/no_think_suffix are applied by CallLLMAPI to final user content, but persisted stage identity previously omitted them; a no-TODO all-Success run might reuse a result from a differently finalized provider prompt. P2: instance bound method with __slots__ has mutable receiver state without __dict__; hashing only __func__ admits stale prompt reuse.
- Controller now binds **only non-secret** model_spec.model_name and no_think_suffix into _extract_stage_provenance_fingerprint on both persistence and resume paths. It does NOT hash the whole model_spec or persist API keys, raw prompts, or endpoints.
- task_fingerprint.py now fails closed for all bound method templates rather than guessing whether a receiver is stateless; standalone functions (including existing attribute-hash support) remain supported. New regression verifies slotted receiver rejection, SQLite/Excel partial Success resume rejection on model finalization drift, and zero-TODO all-Success context drift on model_name and no_think_suffix without extra LLM requests or Success modification.
- Corrective commits b35de0d (model finalization), 10f6877 (bound methods), f1fe005 (regressions). New exact-head CI and Codex re-review are still pending; Windows self-hosted jobs previously queued. PR remains OPEN; no merge without user authorization.

### 2026-10-15 PR #213 fifth Codex review P2 / intrinsic callable metadata (pending validation)
- Exact-head Codex review of a9b26d6 completed with one new P2: function.__doc__ and __annotations__ are mutable intrinsic metadata, invisible to function.__dict__ fingerprint, potentially changing self-referential task templates without invalidating partial/all-Success resume. Previous P1 runtime finalization and P2 slotted bound-method findings were already fixed and resolved; Linux offline E2E at a9b26d6 passed.
- Corrective commit a216dd7 includes mutable __doc__, __annotations__, and __name__ in stable function hash; unsupported annotations fail closed (no stale Success reuse). Existing __module__, __qualname__, code, defaults, closure, referenced globals, and __dict__ remain covered.
- Regression commit 1347fd9 adds fingerprint mutation tests plus SQLite/Excel real-controller partial A Success/B TODO and all-Success zero-TODO provenance invalidation with no LLM redispatch or Success writeback for changed __doc__, __annotations__, or __name__.
- Fifth-round exact-head CI and fresh Codex review still required. PR #213 OPEN; no merge without explicit user approval.

### 2026-10-15 PR #213 sixth Codex review / first-dispatch manifest crash window (pending validation)
- Codex reviewed dc9e5a49 and found one new P2: if original.json source membership is durable but first dispatch_sha256 has not been committed, a changed same-name queued prompt could become the authoritative first dispatch despite verified raw-source parts. Previous dc9e5a49 Linux offline E2E gate passed; Windows self-hosted still queued.
- Scoped single-extract path now records **hashes only** of original queued prompt bytes as initial_prompt_sha256 in the same atomic manifest as source membership (no prompt text/secrets). On resume/smart_reset, original TODO entries without an earlier dispatch hash must match the committed initial hash or the deterministic stage prompt re-rendered from independently verified original source fragments. Missing legacy initial hash fails closed, requiring explicit full_restart. The runner repeats the first-dispatch identity check before adopting the hash; split-child lineage still uses its existing verified split journal.
- Verified full_restart source rebuild refreshes initial_prompt_sha256 for newly generated source prompts when clearing old dispatch identities. Regression added in tests/e2e/test_issue_211_sqlite_excel_writeback_e2e.py: inject interruption immediately after original.json atomic write, before any LLM call, then test modified B TODO, missing-baseline refusal, and untampered recovery on SQLite/Excel and resume/smart_reset (12 scenarios). The existing resume backend parametrization remains intact.
- Corrective commits: 4990893, 678ac9b, d287cf9, 9ba78b4 and 0a294f8. Exact-head CI and fresh Codex re-review still required. PR OPEN; user has not authorized merge.

### 2026-10-15 PR #213 seventh Codex P1 / global risk-criteria fallback identity (pending CI)
- Codex reviewed b439637 and identified a new P1: generate_prompt detects risk-criteria templates via source phrases and, when ctx.keyConsiderations is empty, calls job_config.getKeyConsiderations(). Previously persisted stage fingerprint hashed only the empty ctx field, so resumed all-Success risk writeback could wrongly accept results from a changed process-global risk definition.
- Controller now traces *reachable global taskSetting generate_prompt* dependencies using the already scoped renderer-dependency graph, mirrors generate_prompt's source-based branch ordering (MainFileName before risk criteria), and hashes the actual nonempty job_config.keyConsiderations fallback whenever ctx.keyConsiderations is empty. No interactive getter is called in provenance computation. If fallback cannot be recovered, fails closed and requires explicit ctx.keyConsiderations; raw criterion text is not persisted in source manifests, only the resulting SHA-256 stage identity.
- Added direct fingerprint tests for fallback changes, explicit criteria overriding the global fallback, and missing-value fail closed; expanded SQLite/Excel real controller A Success/B TODO and all-Success regression coverage under resume/smart_reset with changed fallback criterion and zero extra provider dispatch or Success writes.
- Corrective commits 27e56db (implementation), 4da07e4 (regressions). Linux CI and fresh exact-head Codex Review must pass before considering merge. Windows self-hosted historical jobs remain queued. PR OPEN, user has not authorized merge.

### 2026-10-16 PR #213 eighth Codex review: classification criteria, RUNNING/full_restart, missing source members
- Hosted Codex reviewed exact head c4a194c and found two P1s and one P2. P1: global CLASS EXT / CLASS Diff EXT getTextClass(exclusive=...) obtains mutable process-global textClass / exclusiveTextClass not bound to persisted resume stage hash. P1: full_restart rebuilt TODO first, but later RUNNING->TODO recovery could overwrite a newly rendered same-name prompt. P2: source membership committed before first dispatch could omit a TODO file and improperly accept surviving subset.
- Scoped extract controller fix 75aeef6: global prompt fallback identity now mirrors generate_prompt's precedence (MainFileName, risk criteria, then class criteria); hashes actual process-global class text/exclusions without invoking interactive input, fails closed on unavailable fallback. Before verified-source full_restart regeneration, recover existing RUNNING prompts into TODO so fresh source-derived TODO overwrites stale entries (subsequent recovery is a no-op). When original manifest has undispatched source members, require each member's verified TODO to exist, rather than silently skip it.
- Added SQLite/Excel real controller regressions in 22852ba and 78046da: changed CLASS EXT / CLASS Diff EXT criteria on partial A-Success/B-TODO and all-Success zero-TODO resume/smart_reset, missing original TODO immediately after initial source manifest, stale RUNNING during full_restart after criterion change; direct class fingerprint change, exclusivity, and missing-value fail-closed tests.
- This work remains an UNMERGED PR, awaiting exact-head CI and fresh Codex review. No merge without user's explicit approval.

### 2026-10-16 PR #213 ninth exact-head Codex: noninteractive full_restart classification preflight
- Codex reviewed b087f63 (Linux offline E2E PASS), identified P2: when full_restart is used for CLASS EXT or CLASS Diff EXT and job_config.textClass / exclusiveTextClass is unavailable, _rebuild_full_restart_from_verified_source may render prompts first and invoke getTextClass()->input() in an unattended process, before later fingerprint validation can fail closed.
- Correction a660a8d adds _extract_stage_provenance_fingerprint(stage_defs[0].task, ctx) BEFORE ANY full_restart queue recovery, original source regeneration or Success cleanup for single-extract writeback; this deterministically rejects missing global classification or risk fallback without interactive input.
- Added SQLite/Excel x CLASS EXT/CLASS Diff EXT real controller regression 528913d and prompt string repair 34e9692: prepare and interrupt a real stage, leave one old prompt in RUNNING, remove textClass/exclusiveTextClass before full_restart, instrument builtins.input to reject any invocation, assert deterministic ValueError, zero model requests, original queue and durable manifest unchanged.
- New exact-head hosted CI and Codex re-review required. PR remains OPEN; no merge without explicit user authorization.

### 2026-10-16 PR #213 tenth Codex review: interactive input() task templates
- Codex reviewed exact head dab2d307 and found P2: a custom callable extract template may directly load builtins.input(); task_fingerprint previously treated this as an invariant builtin. The new full_restart preflight therefore missed this external, unrecorded prompt dependency and only called input() after queue recovery/mutation.
- Correction 78f1a1e: task_fingerprint._stable_composite rejects LOAD_GLOBAL/LOAD_NAME "input" before looking at referenced module globals/builtins, including inside nested code; do not hash the input builtin as stable. This makes the single-extract full_restart preflight fail closed with deterministic ValueError before touching RUNNING/TODO/Success, and rejects unsupported interactive state in resume.
- Regressions c1557f1 and 4f0d70a: direct and nested input-using template fingerprint rejection, plus a SQLite/Excel real-controller full_restart that changes an already prepared source-manifest task to an input()-using callable with stale RUNNING; assert no interactive calls, zero LLM requests, and byte-for-byte preservation of queue and durable source manifest.
- Await new exact-head Hosted CI and fresh Codex review; PR remains OPEN, not merged without explicit user authorization.

### 2026-10-16 PR #213 eleventh Codex review: effectful builtins in templates
- Codex reviewed exact head bf225aa0 (Linux offline E2E PASS) and found a new P2: task_fingerprint had rejected input() but still considered all other Python builtins stable, permitting open()/breakpoint() and untracked external state during full_restart after queue mutation.
- Correction 58b6e7a changes the fingerprint builtin branch to an explicit, narrow _SAFE_BUILTIN_NAMES allowlist of deterministic argument-based builtins and builtin exception classes; all other builtins fail closed (including open(), breakpoint(), print(), dynamic runtime introspection and process identity). The earlier explicit input() guard, globals/locals/eval/exec rejection, and transitive helper bytecode scan remain in place.
- E2E regressions f7e5c4f / 8bd187a cover direct input, nested input, open, and breakpoint rejection, and a real interrupted SQLite/Excel source manifest with stale RUNNING; switch to each unsafe custom callable for full_restart and assert ValueError BEFORE input / provider dispatch / RUNNING/TODO/Success/provenance writes. Pure str/len/sorted template remains fingerprintable.
- Fresh exact-head hosted CI and Codex re-review are required before PR merge. PR remains OPEN; do not merge without user authorization.

### 2026-10-16 PR #213 twelfth Codex review / noncanonical function builtins namespace
- Codex reviewed exact HEAD 7a10bdd7 and left one new P2 on task_fingerprint.py: custom exec/plugin-created callables can resolve even allowlisted names such as len from a mutable function-specific __builtins__ mapping rather than process builtins. Hashing only the name would reuse stale partial or all-Success output after a custom implementation change.
- Fix 7eb2886: while serializing each statically referenced Python builtin, fingerprint_task now inspects the callable's actual __builtins__ dictionary and requires that symbol's object to be identical to its canonical process builtins attribute; unknown/dynamic/missing/non-dict namespaces fail closed with ValueError, including after a plugin loader modifies the mapping. Existing unsafe-builtin refusal and safe builtin allowlist remain.
- Regression 9131c7a and 3da41b6: in the SQLite/Excel real-controller full_restart test, create a custom template with exec and an explicitly supplied __builtins__ mapping. Verify canonical mapping fingerprints, then replace the function-local len with a custom lambda; both direct fingerprint and preflight refuse before touching old RUNNING/TODO/Success or original.json, with zero provider requests. Also verify input/open/breakpoint cases and safe deterministic builtin use.
- Require fresh exact-HEAD Hosted CI and Codex Review before merging. No merge authorization has been given.

### 2026-10-16 PR #213 thirteenth Codex review: preflight unsafe extract before first dispatch
- Codex reviewed exact Hosted head eff7e7f1d8 (Linux offline E2E PASS) and flagged P2 4291706420: normal fresh/resume/smart_reset single-extract runs may execute an input/open/breakpoint custom template in _prepare_todo_for_stage BEFORE their first provenance digest; only explicit full_restart had been preflighted.
- Fix d2de755: execute _extract_stage_provenance_fingerprint(stage_defs[0].task, ctx) unconditionally for all single-extract writeback policies immediately after resolved stage selection and before split reconciliation, queue moves, source snapshot commits, stage rendering or dispatch. Existing full_restart preflight is now subsumed by the shared call. Unsupported interactive builtins, custom namespace, classification/risk criteria fail closed without side effects.
- Regressions 0753e67/bf7799a: new real SQLite/Excel fresh first-dispatch with unsafe input/open/breakpoint template under resume/smart_reset (no original.json created, unchanged TODO, no requests/input/Success). Expanded previously interrupted manifest/RUNNING + unsafe input/open/breakpoint/noncanonical-len test to all resume/smart_reset/full_restart, asserting no queue mutation or provider calls.
- Fresh exact-head Hosted CI and Codex review required before PR merge. Not merged; user has not authorized merge.

### 2026-10-16 production ES multidim Event two-slice writeback incident
- User runs Qwen via local Ollama-compatible endpoint (no credentials committed) processing an ES multi-dimensional event extract at large scale. Two chunk-local Event entries were independently named E1, generic audited JSON merge concatenated both, and strict ESSink multidim_event profile rejected the writeback ("duplicate event_id 'E1'"). Row Merger left document pending and released in-progress marker, so the model's successful JSON repair was NOT evidence of ES persistence.
- Reviewed actual code in utilities/slice_merge.py, sql_mode/runtime/row_merger_generic.py, utilities/combine_utils.py, prompt_pipeline/pipeline_controller.py, es_mode/output_profiles/multidim_event.py and es_mode/runtime/sinks/es_sink.py. Generic list concat does not understand cross-reference integrity and the source also contained nested Impact ([[dict]]) beyond strict profile shape. Treat these as two separate defects.
- Proposed fix branch fix/es-multidim-event-slice-ids-20261016: add opt-in multidim_event-aware reconciliation BEFORE list concat, allocate collision-free E-prefixed IDs across source fragments while preserving original labels where possible, remap only same-slice linked event_ids (including nested Impact refs), never rewrite original raw/Success payload, and reject ambiguous duplicates within an original slice; apply at Row Merger, combiner and single-extract stage merge. ES output profile format-only flattens one redundant Impact list level while keeping strict schema and referential validation.
- Offline tests added tests/es_mode/test_multidim_event_slice_merge.py including a simulated real row-merger -> strict ES profile writeback and integration into Linux offline-e2e CI. No real user ES or LLM endpoint accessible. At this point tests, CI and new Codex review remain PENDING; no claim of released fix, no direct main modification, do not merge without user consent.

### 2026-10-16 PR #214 first Codex review corrective pass
- Codex exact head c15789b identified P1 #4292956533: single-extract source:stage multidim merged dict lacked required one-element article array envelope; fixed 59db616 to emit [merged] for selected strict article profile while preserving plain dict elsewhere.
- P1 #4292956545: generating new E2 for a colliding E1 could accidentally validate an originally dangling event_ids=["E2"]. Fix 62449d6 collects all known Event IDs AND all linked reference IDs before choosing fresh names; impossible to synthesize a new ID that matches any previously dangling reference.
- P1 #4292956558: whitespace-padded references like " E1 " were not remapped; fix 62449d6 normalizes reference lookup with .strip() exactly as ES strict validator does.
- P2 #4292956567: with multiple writeback rules, any multidim output could incorrectly enable event renaming for a generic flatten-source output; fix 62449d6 resolves only exact selected output's profile, and Row Merger 9984ba3 passes the actual configured flatten selector to the opt-in check.
- Added regressions 567bf48: stage array envelope, unchanged dangling reference failure, padded reference remapping, multi-field flatten selector and preserved generic behavior. Await fresh exact-head CI/Codex, no merge.

### 2026-10-16 PR #214 second Codex review: three data integrity P1s and CI test mismatch
- Reviewed exact HEAD b2453ae: Codex P1 #4293034861 identified cross-slice invalid link becoming valid via a later unrelated event; fix 184c641 adds full per-original-slice local Event ID validation of all linked Person/Involved_Parties/Impact/Event_Timeline/evidence_snippets references BEFORE event-ID renaming. Rejects dangling refs instead of relying on global sink post-merge validation.
- P1 #4293034875: Row Merger's single flattened-source profile was fanned out to all same-source output fields. Fix e115cb7 computes and caches separate generic and multidim merged outputs by destination profile, with correct array envelope for strict article field, and keeps original generic Event IDs untouched. This is exercised under both flatten selectors in actual offline watchdog->ES profile tests.
- P1 #4293034885: one explicit writeback rule with a different top-level ctx.output_col did not select strict output profile. Fix 184c641 selects the sole rule when unspecified, while an explicit output_col argument remains authoritative. Previous CI run 38880380814 failed exactly at the formerly contradictory single-rule test; prior E2E/audit/aggregate/issue211 steps passed.
- A further proactive safeguard e87550a / 6e2bf25 / 87bd4ab keeps original split JSON arrays when mixed-profile same-source destinations are present, both in legacy combiner and one-stage extract stage output; only Row Merger can perform profile-specific recombination without losing original chunk references.
- Offline regression updates 8e2e5f7 / 539a6aa: reject both same-slice or cross-slice dangling references, white-space reference normalization, explicit single-rule profile, mixed field source, real Row Merger under generic and strict flatten selectors, stage defer. New exact-head CI and Codex needed, not merged.

### 2026-10-17 PR #214 third Codex review: omitted secondary ES output profile
- Codex reviewed exact Hosted HEAD 0edae8747f1d and found P1 #4293214497: es_writeback_rules secondary output_col=multidim_event_json with no explicit output_profile must use ESSink's per-field automatic inference; the prior selector inherited ctx.output_profile="none" from the unrelated primary field. This could silently premerge mixed-profile slices and then fail the strict ES schema at writeback.
- Fixed in 4629ad2: is_multidim_event_slice_merge now distinguishes matching rule provenance (ES vs SQL), honors explicitly configured profiles, and uses "auto" for an implicit secondary ES output profile when the selected output name differs from the primary. Preserves explicit output_col target and previous sole-rule selection, and SQL fallback behavior.
- New regression 1bc5ed1 checks mixed generic + implicit multidim ES rules under both combined and stage sources, verifies the stage preserves two input slice rows for later per-field merge, honors explicit output_profile="none" opt-out, and infers sole implicit multidim rule despite unrelated primary output_col. Exact-head Linux CI / Codex review pending; not merged or claimed live ES acceptance.

### 2026-10-17 PR #214 fourth Codex review: source-specific premerge output profile
- Hosted Codex reviewed accepted HEAD 64da060 and flagged P1 #4296920591: when different writeback rules consume different sources, e.g. primary generic_json source=stage and secondary implicit multidim_event_json source=combined, combined-source premerge mistakenly used primary ctx.output_col's generic profile. Because combined had only a strict consumer, mixed-profile defer stayed false but duplicate E1 IDs survived and ES sink rejected writeback.
- Fix 5bfad4e: new is_multidim_event_source_merge(ctx, source=...) selects strict-vs-generic using ONLY the output rules that consume the currently materialized source, with no-rule fallback matching legacy behavior.  e62b43a wires both combined JSON codepaths to source="combined"; 773b103 wires the one-stage stage merge, including its array envelope, to source="stage". The separate mixed-consumer deferral and per-destination Row Merger remain intact.
- Regression 2f48949: stage generic / combined strict (implicit or explicit strict ES profile) tests actual stage artifact and strict source selector, then validates remapped E1/E2 and Person event_ids through the strict ES profile. Regression b939743: calls actual combine_api_finished_item with raw two Success slices and stage generic+combined implicit strict rules; demands combined's correct E1/E2 and strict profile normalization. Existing tests unchanged.
- Latest exact-head Hosted CI and new Codex review required; neither direct live ES validation nor merge has occurred.
