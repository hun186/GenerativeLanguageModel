# 已知問題（Known Issues）

## Current Summary

### Requirements installation is blocked by the network proxy

- **First confirmed:** 2026-06-24; repeatedly reproduced through 2026-09-19.
- `python -m pip install -r requirements.txt` cannot clone the pinned GitHub `peft` dependency because the HTTPS proxy returns `CONNECT tunnel failed, response 403`.
- The incomplete environment commonly lacks PyYAML and sometimes other runtime dependencies, so tests importing the full SQL/ES pipeline can fail during collection rather than from application code.
- Use dependency-light targeted tests, `compileall`, and `git diff --check` as alternative checks, then rerun affected integration/full-suite tests in an environment with the complete requirements.
- **Status:** Open; external network/proxy limitation.

### Historical ES documents may contain model credentials

- Older `_short_tag_from_spec()` behavior could stringify a dict model spec into `<output_col>_meta.model_tag`, potentially persisting API keys or actual endpoint URLs.
- The current allowlist/redaction boundary protects future writes but does not scrub historical ES documents, snapshots, or external logs.
- Operators must rotate exposed credentials and perform a controlled cleanup/reindex while restricting access until cleanup is complete.
- **Status:** Open; requires ES operator action.

### Windows legacy single-stage multiprocessing overlap

- A legacy single-stage LLM round can encounter `EOFError` or `PermissionError: [WinError 5] DuplicateHandle` while creating a multiprocessing pool when another child is active.
- The runtime uses a short reap attempt and a targeted thread-pool fallback to preserve I/O concurrency without broadly changing non-Windows or multistage execution.
- The precise machine-specific handle interaction is not fully established.
- **Status:** Mitigated; retain diagnostic coverage.

### Windows spawn-overlap smoke-test expectation mismatch

- `tests/prompt_pipeline/test_round_runner_smoke.py::test_windows_spawn_overlap_join_clear_allows_pool` expects multiprocessing after reap clears children, while current runtime policy conservatively selects ThreadPool whenever the round observed an active child.
- Decide whether to update the test to the current safety policy or revise that policy after Windows evidence.
- **Status:** Open.

### datetime.utcnow deprecation warnings

- Some test/runtime paths may still emit `datetime.utcnow` deprecation warnings.
- This is not currently a functional failure but should be migrated to timezone-aware UTC values when those paths are next maintained.
- **Status:** Open.

## Recent Changes

- **2026-09-19:** 單獨執行 `python -m pip install PyYAML` 也因 package index proxy 403 無法取得套件；PR B import corrective 因而仍無法收集 multistage/Row Merger regressions，改以 clean subprocess import test、dependency-light suites 與 static checks 驗證。
- **2026-09-19:** PR B requirements 安裝仍在 pinned GitHub `peft` clone 遭遇 `CONNECT tunnel failed, response 403`；multistage/Row Merger tests 因缺少 PyYAML 無法 collection。Dependency-light reducer tests、PR A combine tests 與 static checks 通過。
- **2026-09-18:** Requirements installation still fails at the GitHub `peft` clone with proxy 403; Row Merger regression collection consequently stops on missing PyYAML. Dependency-light combine tests and static checks remain available.
- **2026-09-01:** LLM audit propagation work reconfirmed the same `peft` proxy limitation; targeted audit tests passed.
- **2026-08-26:** ES mapping retry-loop and consequence validation work reconfirmed the dependency limitation; dependency-light ESSink/profile tests passed.
- **2026-08-20:** Row Merger schema-failure integration tests could not collect because requirements installation failed and PyYAML/numpy were absent; direct profile checks and compile checks were used.
- **2026-07-20:** YAML parsing and some prompt-pipeline tests were unavailable without PyYAML; Windows spawn-overlap test expectation mismatch was recorded.
- **2026-07-17:** Windows multiprocessing overlap was narrowed to pool creation with active children and mitigated with targeted reap/thread fallback.

## Archived History

- `.codex/archive/known_issues-20260918-000000.md` — archived 2026-09-18; complete pre-compaction history covering dependency installation, SQL/ES Row Merger collection limits, Windows multiprocessing investigation, metadata credential risk, and resolved/superseded notes.

## 2026-09-19 Reduction Engine PR C environment verification

- Requirements 安裝再次在 pinned GitHub `peft` clone 遭 proxy 403；Row Merger/multistage suite 因缺少 PyYAML 在 collection 停止。Reduction/PR A dependency-light suites、compileall 與 static checks 作為替代驗證。

## 2026-09-20 Reduction Engine PR D2 environment verification

- Required dependency installation was retried. `pip` itself was already present, but `python -m pip install -r requirements.txt` again failed while cloning pinned GitHub `peft` because the network proxy returned `CONNECT tunnel failed, response 403`.
- Dependency-light Reduction and characterization suites remain the available validation path in this environment; no production bypass was added. The combined prompt-pipeline selection containing `test_prompt_pipeline.py` could not collect because `opencc` is absent after the blocked install; dependency-light dispatch/audit tests were run separately.

## 2026-09-20 Reduction Engine PR D2 hosted-review corrective environment verification

- Requirements installation was retried for the P1 corrective and remains blocked at the pinned GitHub `peft` clone by proxy `CONNECT tunnel failed, response 403`. The corrective therefore uses the required dependency-light regression suites without changing production dependency behavior.
- The final two-pass retry/runtime-v2 corrective reconfirmed the same proxy failure. No dependency workaround was added; required dependency-light reduction, characterization, prompt dispatch/audit, compile, and diff checks completed successfully.

## 2026-09-20 Reduction Engine PR E environment verification

- Required dependency installation was retried after upgrading/checking pip and again failed cloning pinned GitHub `peft` because the proxy returned `CONNECT tunnel failed, response 403`. No production dependency bypass was added.
- Installed dependency-light suites remained usable: all required PR E reduction, dispatch, producer, D2, characterization, compileall, and diff checks passed. Pytest emitted the existing non-fatal warning that `env_files` is an unknown config option in this incomplete environment.

## 2026-09-20 Offline E2E dependency blocker

- The sandbox lacks `pandas`, `openai`, `elasticsearch`, `pyodbc`, PyYAML, and numpy. The required installation still stops at the pinned GitHub `peft` clone because the proxy returns 403, so `python -m pytest -q -m e2e` currently stops during collection on missing `pandas` here.
- Once declared runtime dependencies are installed, the suite needs no remote infrastructure: LLM traffic is localhost-only, SQL is file-backed SQLite, and ES scan/bulk storage is in memory.
- Status: open environment blocker; no application dependency bypass was introduced.

## 2026-09-20 PR #185 corrective dependency verification

- The dependency-light `python -m pip install -r requirements-e2e.txt` also cannot reach the configured package index in this sandbox (proxy 403 beginning with `colorama`), so offline E2E execution remains unavailable locally. This is broader than the pinned GitHub `peft` failure and requires hosted/self-hosted CI with package access.

## 2026-09-20 Scheduler source-backup warning

- Hosted offline ES scheduling logged a non-fatal source TXT backup warning for `/cache` after the affected row otherwise completed through LLM and ES writeback. It is not part of the headless-stdin failure and remains a follow-up only if it becomes a functional failure after countdown hardening.

## 2026-09-24 Reduction Engine PR F environment verification

- The required `pip`/requirements setup was retried. `requirements.txt` again failed while cloning the pinned GitHub `peft` revision because the proxy returned HTTP 403; no dependency bypass was added.
- Dependency-light PR F tests, all reduction tests, compileall, and diff checks pass. Offline E2E collection and execution stop during import because PyYAML is absent after the blocked installation; hosted CI with the declared E2E dependencies must provide the 13-case acceptance result.
- PR F identity-safety corrective 再次執行 requirements setup，仍在 pinned GitHub `peft` clone 遭 proxy HTTP 403；focused 34 tests、全 reduction 175 tests 與 static checks 通過，corrected head 的 offline E2E 必須由 hosted Actions 重跑。

## 2026-09-24 PR G environment verification

- Requirements installation again failed cloning pinned GitHub `peft` through the proxy (HTTP 403). Focused dependency-light collection tests pass; broad SQL/ES regression collection stops on missing `numpy`, and the offline E2E gate must run in hosted CI. No runtime dependency bypass was introduced.

## 2026-09-29 PR G corrective environment verification

- Requirements installation remains blocked at the pinned GitHub `peft` clone by proxy HTTP 403. Dependency-light reduction and focused SQL/ES tests pass, and the two new PR G E2E tests pass directly; the complete hosted E2E count/result remains required before PR G is marked complete.

## 2026-09-29 final PR G corrective environment verification

- Requirements installation remains blocked by proxy HTTP 403 at pinned `peft`. All dependency-light required suites and focused PR G E2E pass locally; authoritative full 15-case E2E still requires hosted CI.

## 2026-09-30 PR H environment and hosted acceptance

- Required dependency installation still fails because the configured proxy returns HTTP 403 for the pinned GitHub `peft` clone. Installed dependency-light tests remain usable; no dependency bypass was introduced.
- PR #188 passed the expanded 16-case offline E2E gate and merged; PR H is complete.
- PR #188 corrective requirements installation was retried and remains blocked locally by the same proxy HTTP 403 on pinned `peft`; dependency-light reduction and focused collection aggregate E2E remain available.
- PR #188 immutable-payload corrective passed the hosted 16-case offline E2E gate and merged; only the recurring local pinned-`peft` proxy limitation remains relevant.

## 2026-09-30 PR I local environment

- Full requirements installation remains blocked by proxy HTTP 403 cloning pinned `peft`; dependency-light E2E installation is also blocked reaching the package index. Reduction tests run, but focused production E2E cannot import `PromptGenerator` because `psutil` is unavailable. Hosted CI must run the 17-case gate; no semantic core fake replaces it.

- Existing PR #189 is the authoritative PR I review surface; its corrected hosted 17-case acceptance remains pending.

## 2026-09-30 PR #189 corrective local verification

- Full requirements installation remains locally blocked by proxy HTTP 403 while cloning pinned `peft`. This does not supersede authoritative hosted PR #189 state, where isolated E2E dependencies install successfully.

## 2026-10-01 PR #189 hosted E2E assertion corrective

- Hosted run #428 (`36690681140`) collected all 17 E2E cases and reached the semantic production request. Its semantic case failed only because the test inspected the fixed message index `0`, which is the existing system message; production sends the semantic prompt as the user-role message. The corrective selects exactly one `role == "user"` message and does not modify production code.
