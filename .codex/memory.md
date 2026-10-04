# Project Memory

## Current Summary

- This Python project processes TXT/Table/SQL/ES inputs through prompt, multistage, reduction, and writeback infrastructure.
- Reduction Engine PR K, L1, and L2a are merged. L2b is implemented on the current feature branch but remains incomplete until fresh hosted 23-case acceptance and merge. L3 is not implemented.
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
