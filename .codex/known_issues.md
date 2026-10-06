# 已知問題（Known Issues）

## Current Summary

### Requirements installation is blocked by the network proxy

- `python -m pip install -r requirements.txt` can fail while cloning the pinned GitHub `peft` dependency because the configured HTTPS proxy returns HTTP 403.
- Incomplete local environments may then lack PyYAML, OpenCC, tqdm or other runtime dependencies, causing broader SQL/ES/prompt suites to fail during collection rather than from application behavior.
- Use dependency-light targeted tests, `compileall`, and `git diff --check` locally, then use hosted `offline-e2e` as the authoritative full production gate.
- **Status:** Open; external network/proxy limitation.

### Historical ES documents may contain model credentials

- Older model-tag behavior could persist stringified model specs containing API keys or actual endpoint URLs.
- Current allowlist/redaction protects future writes but does not scrub historical documents, snapshots or external logs.
- Operators must rotate exposed credentials and perform controlled cleanup/reindex while access is restricted.
- **Status:** Open; requires ES operator action.

### Windows legacy single-stage multiprocessing overlap

- A legacy single-stage LLM round can encounter `EOFError` or `PermissionError: [WinError 5] DuplicateHandle` when creating a multiprocessing pool while another child is active.
- Runtime uses a short reap attempt and targeted thread-pool fallback without broadly changing non-Windows or multistage execution.
- **Status:** Mitigated; retain diagnostic coverage.

### Windows spawn-overlap smoke-test expectation mismatch

- `tests/prompt_pipeline/test_round_runner_smoke.py::test_windows_spawn_overlap_join_clear_allows_pool` expects multiprocessing after reap clears children, while current safety policy selects ThreadPool whenever the round observed an active child.
- Decide whether to update the test or policy after Windows evidence.
- **Status:** Open.

### datetime.utcnow deprecation warnings

- Some paths may still emit `datetime.utcnow` deprecation warnings.
- Migrate those paths to timezone-aware UTC values when next maintained.
- **Status:** Open; non-functional warning.

## Recent Changes

### 2026-10-06 Reduction retention bounded-reporting issue resolved

- Historical issue: a malformed tombstone encountered after deletion-budget exhaustion could be counted in `scanned` without incrementing `skipped_invalid`.
- PR #201 added a run-local `deletion_budget_exhausted` latch so later candidates still undergo validation/classification/counters while no further deletion occurs.
- Accepted head `62deba6a35d5d5f1d5c82f586d65bc8827e212ef`; CI #459 / `37399753801`; offline job `112064086574`; collect 24; full gate PASS / 100%; merge `91e39503c8e84d17752f9d26a23ff6b34db75b9e`; signature verified / valid.

### 2026-10-04 to 2026-10-06 local verification environment

- Required dependency installation continued to be proxy-limited; dependency-light Reduction/retention/prompt checks remained available while hosted offline E2E supplied authoritative acceptance for L2/L3 and closure heads.

## Archived History

- `.codex/archive/known_issues.md-20261006-134200.md` — complete pre-compaction issue/environment history through PR #200 head `39177737486a372f38e9b6d81563d6f14327459a`.
- `.codex/archive/known_issues-20260918-000000.md` — earlier pre-compaction history retained.
