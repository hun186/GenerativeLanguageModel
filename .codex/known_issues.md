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

- PR #189 subsequently passed the authoritative hosted 17/17 offline E2E gate and merged as `ea3f8b4436000cbc201cd63da2a2db3259b4ab5b`; it is no longer pending.

## 2026-09-30 PR #189 corrective local verification

- Full requirements installation remains locally blocked by proxy HTTP 403 while cloning pinned `peft`. This does not supersede authoritative hosted PR #189 state, where isolated E2E dependencies install successfully.

## 2026-10-01 PR #189 hosted E2E assertion corrective

- Hosted run #428 (`36690681140`) collected all 17 E2E cases and reached the semantic production request. Its semantic case failed only because the test inspected the fixed message index `0`, which is the existing system message; production sends the semantic prompt as the user-role message. The corrective selects exactly one `role == "user"` message and does not modify production code.

## 2026-10-01 PR J local environment

- PR #189 / PR I is complete: hosted offline E2E 17/17 passed and merge commit is `ea3f8b4436000cbc201cd63da2a2db3259b4ab5b`.
- The recurring full `requirements.txt` pinned-`peft` proxy limitation remains historical/open. PR J's dependency-light reduction, Output Profile, and focused SQLite E2E checks run locally; fresh hosted 18-case acceptance is required before checking off PR J.
- PR J setup retry: `python -m pip install --upgrade pip` found pip installed but the configured index was proxy-blocked; `python -m pip install -r requirements.txt` then failed cloning pinned `peft` with `CONNECT tunnel failed, response 403`. Consequently full `tests/e2e` collection stops at missing `yaml`; focused PR J E2E passes with installed dependencies, and hosted `offline-e2e` remains authoritative.

## 2026-10-01 PR K1 local environment

- Required setup was attempted. The configured package index and pinned GitHub `peft` clone were blocked by proxy HTTP 403; the environment also lacks `tqdm`, so the focused production HTTP K1 E2E cannot locally import the real tokenizer stack. Dependency-light reduction tests and compile checks remain available; hosted `offline-e2e` is the authoritative 19-case gate.
- Windows self-hosted runners remain unprovisioned and outside the acceptance gate.
- Hosted publication is also blocked in this environment: pushing `feat/reduction-stage-executables-k1` to `https://github.com/hun186/GenerativeLanguageModel.git` fails with `CONNECT tunnel failed, response 403`. Therefore no hosted PR number or fresh hosted run ID can be collected locally; retry push/PR creation and the 19-case gate from a network-enabled environment.

## 2026-10-01 PR #191 corrective environment

- The required requirements installation remains proxy-blocked at the pinned GitHub `peft` clone (HTTP tunnel 403). Dependency-light unit/regression checks run locally; the real-tokenizer K1 E2E and fresh hosted 19-case acceptance require the hosted environment.

## 2026-10-01 PR #191 final corrective environment

- Required dependency installation remains blocked by the pinned GitHub `peft` proxy 403, so the focused production E2E requires hosted execution. This does not affect dependency-light K1 and prompt-stage regressions.
# 2026-10-02 PR K2 local environment limitation

- Required `python -m pip install --upgrade pip` completed, but `python -m pip install -r requirements.txt` remains blocked by the sandbox CONNECT proxy (HTTP 403 while cloning pinned GitHub `peft`).
- Dependency-light K2/reduction/prompt tests run locally. The focused production K2 E2E cannot collect locally because the incomplete install leaves `psutil` unavailable while importing the real tokenizer production path; hosted `offline-e2e` must provide the fresh 20-case acceptance evidence.
- Alternative validation: focused K2 unit suite, full reduction suite, prompt-pipeline regressions, compileall, and diff checks. No production behavior is replaced by a mock to hide this limitation.
- This checkout has no configured `origin` repository, so `git push -u origin feat/reduction-stage-nesting-k2` fails before network/authentication and no hosted PR number or fresh CI run can be obtained from the container. PR metadata was prepared with `make_pr`; an environment with the repository remote must push the committed branch and run the 20-case gate.

## 2026-10-02 PR #192 hosted K2 corrective findings

- Rejected head `16487e4769e7d7fa4b1c7763c5efc25049460854`, CI #438 / `36964059859`, collected 20 E2E cases but failed because raw tokenizer chunks did not account for final rendered-prompt overhead.
- Review found that concurrent identical inputs through one checkpointed nested executable could interleave D1 payload/checkpoint pair writes; K2 uses conservative per-instance serialization without changing D1/D2 formats.
- The K2 E2E incorrectly treated expected `audit.csv`/`audit.xlsx` telemetry as forbidden business writeback; assertions are narrowed to actual sink artifacts.
- The earlier K2 `.codex` compaction was out of scope and has been reverted. Fresh hosted 20/20 acceptance remains required.

## 2026-10-02 PR L1 local environment

- Required `python -m pip install --upgrade pip` / `python -m pip install -r requirements.txt` cannot complete because the environment's HTTP tunnel returns 403 while cloning pinned GitHub `peft`. Dependency-light focused tests and compileall remain the local alternative; hosted offline E2E is required for the full 21-case gate.
- Consequently, local `tests/sql_mode` stops during collection on missing `numpy`, local `tests/es_mode` stops on missing `elasticsearch`, and the production L1 E2E cannot execute. `tests/sql_mode/test_sql_collection.py tests/es_mode/test_es_collection.py` also exposes a pre-existing SQL grouped collection expectation (`all` versus deterministic grouped collection ID) unrelated to L1. Hosted CI remains the authoritative 21-case acceptance gate.

## 2026-10-02 PR #193 corrective environment

- Required dependency installation was retried and remains blocked by HTTP tunnel 403 for pinned GitHub `peft`. Dependency-light focused/reduction tests remain available; full local SQL/ES and production E2E require the hosted dependency environment.
- Corrective verification impact: `tests/sql_mode` cannot collect without numpy, `tests/es_mode` cannot collect without elasticsearch, and `tests/e2e/test_persisted_reuse_l1_e2e.py` cannot collect without PyYAML. Focused dependency-light contracts cover the corrective locally; this is not hosted acceptance.

## 2026-10-03 PR #193 final corrective environment

- Required requirements installation remains blocked by the pinned GitHub `peft` HTTP tunnel 403. Dependency-light final-corrective tests are available; complete ES/reduction verification is attempted separately and hosted 21-case acceptance remains authoritative.
- `python -m pytest -q tests/es_mode --maxfail=1` remains unable to collect `test_steps_es_adapter_replacements.py` because `elasticsearch` is unavailable after the proxy-blocked requirements install. Focused pure/fake-client ES freshness discovery tests pass and compileall is the local alternative.

## 2026-10-04 PR L2a local environment limits

- Required `python -m pip install --upgrade pip` could not reach the configured package index through the environment tunnel (HTTP 403 retries), though the existing pip remained usable.
- Required `python -m pip install -r requirements.txt` again failed cloning pinned GitHub `peft` because the CONNECT tunnel returned HTTP 403. The dependency-light focused and regression suites run locally; the new production fake-OpenAI L2a E2E cannot start locally because the incomplete environment lacks `tqdm`. Fresh hosted `offline-e2e` is required for authoritative collect-only 22 and full 22/22 evidence.
- Complete local E2E collect-only additionally stops while importing the ES boundary because PyYAML is absent. This is the same incomplete-install limitation; hosted CI remains the alternative verification.
