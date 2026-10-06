# Project Memory

## Current Summary

- This Python project processes TXT/Table/SQL/ES inputs through prompt, multistage, reduction, and writeback infrastructure.
- **Reduction Engine v1 is COMPLETE / RELEASE-READY.** A–L is complete, the L3 retention reporting release-audit corrective was accepted and merged through PR #201, and the PR #200 documentation closure reconciliation head passed its fresh hosted 24-case gate. Authoritative runtime baseline is verified `main` merge `91e39503c8e84d17752f9d26a23ff6b34db75b9e`; PR #200 remains unmerged pending fresh review and explicit merge approval.
- PR #201 authoritative evidence: accepted head `62deba6a35d5d5f1d5c82f586d65bc8827e212ef`; CI #459 / `37399753801`; offline job `112064086574`; collect 24; full gate PASS / 100%; merge `91e39503c8e84d17752f9d26a23ff6b34db75b9e`; signature verified / valid. PR #200 release-state declaration head `8d283b369da2989535c109fa4f046b2c7ba57f31` passed CI #463 / `37402351444`, offline job `112072129880`, collect 24 and full gate PASS / 100%.
- L2a authoritative evidence: PR #195, accepted head `f4ad4001f4498287799df3c89e90ff4a733dc572`, CI #448 / `37179982321`, offline job `111370415206`, collect 22 and full PASS, merge `c1f2f6974e88028eb3eb5b9b747fefeb8d6d5cf0`, verified/valid signature. PR #194 is closed/unmerged/superseded.
- Production operator cancellation is cooperative and distinct from worker teardown. It stops new scheduling and semantic continuation while allowing in-flight external calls and existing consumer/merger/writeback work to drain.
- Production Reduction observability uses allowlisted bounded JSONL, lock-protected counters, and a separate Windows GUI Reduction Status panel.
- Required dependency installation remains blocked by the pinned GitHub `peft` clone proxy 403. Dependency-light tests are locally available; hosted offline E2E is authoritative.

## Recent Changes

### 2026-10-06 Windows GUI live observability / compact status fix

- Fixed Recheck GUI freshness for slow SQL/ES jobs: the first dispatch recheck publishes immediately, then updates on either the existing count threshold or a default 1-second time threshold, with final forced delivery. Run-scoped locking serializes cumulative stats plus time-based GUI publication under multistage row parallelism so snapshots cannot regress or defeat the throttle; GUI queue failures are swallowed locally and cannot alter pending decisions or scheduling.
- Made Reduction GUI mode-aware. Legacy slice-merge activation uses the same canonical `should_merge_slices()` predicate as execution (including `merge_slices`, `enable_slice_merge`, and supported `merge_strategy` aliases), then reports dedicated merge attempt/completion/failure counters from the actual row-merger combine path (with the fallback sweep still covered) instead of misleading Stage/Member 0/0 values; observer activity-mode transitions force-publish to the GUI. Legacy telemetry is gated on the real merge_slices switch, row-merger/fallback share one run-scoped claim so the same item cannot be merged or counted twice, failed claims are released for retry, and premerged multistage `CombBackFN` dict outputs are explicitly accounted when Row Merger confirms the combined-source writeback.
- Recheck Status and Reduction Status are collapsible by default with one-line header summaries. The Reduction Cancel control remains visible while collapsed.
- Regression coverage locks the first/time-based recheck snapshots, legacy merge observer counters, mode-aware formatting, and collapsible source contract.

### 2026-10-06 Active project-memory compaction

- Compacted `.codex/architecture.md`, `.codex/api_contract.md`, `.codex/known_issues.md`, `.codex/decisions.md`, and `.codex/backlog.md` because each exceeded the AGENTS.md threshold of 20 dated/work blocks.
- Preserved each complete pre-compaction file first under `.codex/archive/*-20261006-134200.md`, then rewrote active files to current summaries, recent relevant changes, and archive references.
- Preserved unresolved issues, open backlog items, current API contracts and still-effective architecture decisions. Superseded point-in-time PR status remains available in the archives.
- Verification passed on compaction head `a795e8c2a632ebe4a329b27c489a1723820ca85a`: each new archive blob SHA exactly equals its pre-compaction source blob SHA (`architecture` `2575101c…`, `api_contract` `6df215ab…`, `known_issues` `07e77c6c…`, `decisions` `5674d347…`, `backlog` `8f549cf8…`). Active heading/work-block counts are architecture 8, api_contract 15, known_issues 10, decisions 7, and backlog 8, all below the >20-block compaction trigger. The follow-up evidence-only commit still requires fresh hosted 24-case acceptance and fresh Codex review before merge readiness.


### 2026-10-06 PR #200 fresh closure acceptance

- Initial documentation reconciliation head `06f0c6b0a6443999a7241b6e5cce0736cde71d38` passed CI #462 / `37401880432`, offline job `112070871594`, collect 24 and full gate PASS / 100%.
- The release-state declaration was then recorded on head `8d283b369da2989535c109fa4f046b2c7ba57f31`; that exact head independently passed CI #463 / `37402351444`, offline job `112072129880`, collect 24 and full production E2E PASS / 100%.
- Reduction Engine v1 may therefore be recorded as COMPLETE / RELEASE-READY. A later review/documentation wording correction must still pass its own fresh exact-head gate before PR #200 is merge-ready; explicit merge approval remains required.

### 2026-10-06 L3 release-audit corrective accepted

- PR #201 corrected truthful bounded-retention reporting with the run-local `deletion_budget_exhausted` latch: after deletion budget exhaustion, validation/classification/counters continue and deletion stays disabled for the rest of the sweep.
- Deterministic regressions cover a later malformed tombstone and the case where a large artifact exhausts the byte budget before a smaller candidate. Hosted acceptance: head `62deba6a35d5d5f1d5c82f586d65bc8827e212ef`, CI #459 / `37399753801`, offline job `112064086574`, collect 24, full gate PASS / 100%.
- PR #201 merged as verified/valid `91e39503c8e84d17752f9d26a23ff6b34db75b9e`. PR #200 is now the sole remaining Reduction Engine v1 closure work and must pass a fresh hosted 24-case gate on its updated documentation head before merge.

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
