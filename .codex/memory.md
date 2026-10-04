# Project Memory

## Current Summary

- This Python project processes TXT/Table/SQL/ES inputs through prompt, multistage, reduction, and writeback infrastructure.
- Reduction Engine PR K, L1, L2a, and L2b are merged. L3 is implemented on the current feature branch but remains incomplete until fresh hosted 24-case acceptance and explicit merge approval.
- L2a authoritative evidence: PR #195, accepted head `f4ad4001f4498287799df3c89e90ff4a733dc572`, CI #448 / `37179982321`, offline job `111370415206`, collect 22 and full PASS, merge `c1f2f6974e88028eb3eb5b9b747fefeb8d6d5cf0`, verified/valid signature. PR #194 is closed/unmerged/superseded.
- Production operator cancellation is cooperative and distinct from worker teardown. It stops new scheduling and semantic continuation while allowing in-flight external calls and existing consumer/merger/writeback work to drain.
- Production Reduction observability uses allowlisted bounded JSONL, lock-protected counters, and a separate Windows GUI Reduction Status panel.
- Required dependency installation remains blocked by the pinned GitHub `peft` clone proxy 403. Dependency-light tests are locally available; hosted offline E2E is authoritative.

## Recent Changes

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
