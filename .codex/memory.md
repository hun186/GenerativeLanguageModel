# Project Memory

## Current Summary

- 本專案是 Python 多來源文件／表格處理與 LLM 多階段分析框架；TXT/Table/SQL/ES 共用 prompt、LLM、combine 與 writeback 基礎設施。
- `combine_api_finished_item()` 是 production 單一文件 Success slice 合併邊界；Row Merger 只負責下游協調，Output Profile 維持最終嚴格驗證。
- Reduction Engine PR A-E 已完成；PR F 已實作 immutable Logical Work Unit / Collection Manifest contract，等待 hosted offline E2E 驗證。PR G 與後續 roadmap 仍未實作。
- Hierarchical round 1 直接 reduce 原始 Success map outputs；round 2+ 才經 tokenizer、configured round task prompt、LLM map 與 concat reducer。
- Requirements 安裝在目前環境仍受 pinned GitHub `peft` proxy 403 限制；dependency-light pytest、compileall 與 diff checks 是可用替代驗證。

## Recent Changes

### 2026-09-24 Reduction Engine PR F collection identity contracts

- 新增 source-independent `LogicalWorkUnit` 與 `CollectionManifest` v1；caller 必須提供穩定 unit/collection identity，manifest 保留 caller-supplied unit order，ordered units、payload 與安全 provenance 都參與 normalized-JSON SHA-256 fingerprint。
- 所有巢狀 JSON values 在建構時 defensive-freeze（mapping proxy + tuple），序列化回傳 detached structures；strict reconstruction 驗證 exact schema、contract version、duplicate unit IDs 與 persisted fingerprint，不生成、修復或重排 identity。
- Provenance 拒絕 credential/model-spec/raw endpoint 與 timestamp/host/PID/session/temp-path 等 runtime identity 欄位。Collection Manifest 與 business stage manifest 維持分離；沒有 SQL/ES adapter、aggregate writeback、production route 或 reducer expansion。
- 驗證：focused collection tests 27 passed；完整 `tests/reduction` 168 passed；compileall 與 `git diff --check` passed。完整 requirements 安裝仍被 GitHub proxy 403 阻擋，offline E2E collect/run 因缺少 PyYAML 無法在本機執行，須由 hosted CI 完成。

### 2026-09-20 Reduction Engine PR E shared execution budget

- Added a source-agnostic process-local `ExecutionBudget` with strict positive-int validation, blocking partial leases, exact finally-release, immutable snapshots, and peak-use observation. Root/run capacity precedence is explicit root, explicit model profile, maximum existing desired process/row/slice width, then 1.
- Root CLI creates one private budget after concurrency projection. `call_llm_api()` and legacy streaming `run_round()` lease only around leaf pools; multistage row orchestration caps thread count without retaining permits. D2 context fallback shares root identity and fingerprints remain capacity-independent.
- Local row and slice policies remain intact; a 2-process/8-slice long document retains capacity 8, while concurrent leaf batches share that ceiling. Scope remains one process; PR F and later roadmap work are not implemented.
- Verification: PR E focused selection 33 passed; all `tests/reduction` 139 passed; dispatch policy 17 passed; producer parallelism 4 passed; D2 runtime/routing 22 passed; compatibility characterization 29 passed; compileall and diff check passed. Requirements install remains blocked by pinned GitHub `peft` proxy 403.

### 2026-09-20 Reduction Engine PR D2 final hosted-review corrective

- 恢復 production 單階段既有的兩階段 LLM retry 契約：同一個 `next_round_items()` 先以 `allow_to_retry=True` dispatch，再以 `False` dispatch 剩餘 TODO，之後才判定 incomplete；兩次 dispatch 仍只是一個 D1 map round。
- `TEXT_ROUND_RUNTIME_CONTRACT_VERSION` 升為 `reduction-text-round-v2`，使 context isolation/newline/retry 語意與 pre-corrective v1 產生不同 execution fingerprint 與 D1 run identity；未修改 D1 checkpoint contract/version，也不遷移 v1 D2 checkpoints。
- Retry regression 驗證 call order、兩次 `task_override`、first-pass 成功項目不重跑、second-pass transient recovery、第二次後仍 incomplete 的明確失敗、context isolation 與兩次完成結果的 newline preparation。Fingerprint regression 驗證 v2 metadata、v1/v2 fingerprint 與 run key 不同。
- 驗證：D2 focused 54 passed；retry-specific 2 passed；runtime-v2 fingerprint-specific 1 passed；全 `tests/reduction` 120 passed；PR A compatibility 29 passed；prompt dispatch/audit 11 passed；compileall 與 diff check 通過。Requirements 安裝仍受 pinned GitHub `peft` proxy 403 阻擋。PR D/D2 保持 awaiting hosted-head review，PR E 與後續 roadmap 未引入。

### 2026-09-20 Reduction Engine PR D2 hosted-review corrective

- 修正 row-scoped slot overlay 的 context isolation：移除 `copy.copy(ctx)`，改用 D2-local attribute view；`round_task` 與任何 derived-context writes 均不會修改 base ctx 或其 mutable override mapping。
- 修正 post-initial concat preparation：LLM Success text 保留原內容，缺少尾端換行時補一個換行，已有換行不重複添加，避免多個 map outputs 被串成 `foobar`。
- Regression coverage 包含 ordinary/slot-overlay context、success 與 tokenizer/prompt/dispatch failure、共享 base context 的雙 adapter 隔離、newline preservation，以及 fixed round-2 多輸出 boundary。
- Requirements 安裝仍受 pinned GitHub `peft` proxy 403 阻擋。D2 config/runtime/routing focused tests 51 passed；全 `tests/reduction` 117 passed；PR A compatibility guards 29 passed；prompt dispatch/audit tests 11 passed；compileall 與 diff check 通過。PR E 與後續 roadmap 未引入。

### 2026-09-20 Reduction Engine PR D2 production hierarchical routing

- 任務目的：把 D1 controller/checkpoint core 接入 production text combine path，完成 PR D，但不提前實作 PR E 或 collection/Stage 架構。
- 主要修改：嚴格 `ReductionConfig` 新增 text-only `fixed_rounds` / `adaptive_hierarchical`、controller options 與必要 `runtime.round_task`；新增 versioned `TextRoundRuntimeAdapter`，以 non-mutating context view 執行 tokenizer → prompt → existing LLM dispatch，workspace 隔離在 `<item>/.reduction/runtime/`。Checkpoint root 為 `<item>/.reduction/checkpoints`。
- 契約結論：既有 Success outputs 完成 round 1，round 2 才第一次執行新 map；adapter 禁止呼叫 `process_prompt_and_merge()`/combine。Execution fingerprint 涵蓋 template/task context/tokenizer/model/generation/think/mock 語意，排除 credentials 與 raw endpoint URL。
- 驗證結果：D2 focused tests 44 passed；全 `tests/reduction` 110 passed；PR A compatibility guards 29 passed；prompt dispatch/audit tests 11 passed；compileall 與 diff check 通過。Requirements 安裝因 pinned GitHub `peft` proxy 403 失敗；包含 `test_prompt_pipeline.py` 的選取因缺少 `opencc` 無法 collection。
- 歷史範圍結論：首次實作當時視為 PR D1 + D2 完成；其後 hosted review 發現的兩項 P1 已由上方 corrective 修正，目前須待更新 hosted head review 才可視為 merge-ready。PR C single-pass 與其他 protected boundaries 未重新設計，PR E 保持 open。

### 2026-09-19 Reduction Engine PR D1 controller/checkpoint core

- 建立 fixed/adaptive controllers、text-only facade、Unicode-character convergence、atomic completed-round checkpoints，以及 strict resume validation。
- Hosted corrective 強制 checkpoint caller 提供 deterministic execution fingerprint，並將 checkpoint contract 升至 v2。
- D1 本身不接 production config/combine；該責任已由 D2 完成。

### 2026-09-19 Reduction Engine PR C single-pass routing

- 新增 immutable strict `ReductionConfig`、三個 explicit single-pass profiles 與 combine-boundary opt-in routing；inactive behavior 不變。
- Hosted corrective 確保 JSON repair 在 reducer 前執行，explicit reducer output 不再進 legacy JSON post-processing。

### 2026-09-19 Reduction Engine PR A/B foundation

- PR A 凍結 Success lexical ordering、text/JSON combine、slice merge、Row Merger 與 Output Profile behavior。
- PR B 建立 source-agnostic reducer contracts、registry、concat text/list 與 legacy deep-merge adapters，並維持 lightweight import boundary。

### 2026-09-18 authoritative premerged multidim writeback

- Row Merger 保留 resolved structured source；authoritative combined dict 可正確套用 generic/multidim serialization，而 stage-specific invalid dict 仍由 profile 拒絕。

### 2026-09-01 LLM call audit propagation

- Legacy consumer 與 stage-managed workers 共用 audit metadata propagation；JSON repair/split retry 子呼叫也保留同一 run/path。

### 2026-08-20 to 2026-08-26 merge and ES validation

- Audited merge 結果成為 authoritative writeback payload，retry 不重複輸出同一 item 的 merge audit。
- Output-profile validation errors 結束本輪確定性重試；ES mapping 400 不再無限重送。`Event.consequence` object 在 ES I/O 前被拒絕。

### 2026-07-17 to 2026-08-21 runtime stability

- Windows legacy pool overlap 以 short reap/thread fallback 緩解；LLM audit、active context metadata、independent slice parallelism、model-profile defaults 與 ES prefetch-off policy 已落地。

### 2026-09-20 Memory Compaction

- `.codex/memory.md` 與 `.codex/decisions.md` 因超過 20 個日期／工作區塊而依規範濃縮。
- 濃縮前全文分別保存於 `.codex/archive/memory.md-20260920-013654.md` 與 `.codex/archive/decisions.md-20260920-013654.md`；以 heading count、檔案存在與 diff check 驗證。

## Archived History

- `memory.md-20260920-013654.md` — complete project-memory history through PR D2 before this compaction.
- `memory.md-20260826-041906.md` — earlier full project-memory snapshot.
- `decisions.md-20260920-013654.md` — complete decision history through PR D2 before this compaction.

### 2026-09-20 Post-PR-E offline production E2E gate

- Added `e2e`/`live_llm` markers and a localhost `ThreadingHTTPServer` with deterministic prompt rules and concurrency/request recording.
- Added production-boundary coverage for TXT filesystem IO, CSV `CSVSink`, file-backed SQLite pending selection plus `SqlSink`, real Elasticsearch adapter selection plus real `ESSink` for single/dual indexes, deterministic routing, and HTTP concurrency under `ExecutionBudget`.
- ES replaces only scan/bulk storage transport with an in-memory dictionary. No GPU, remote LLM, MSSQL, ES server, credentials, internet, or PR F behavior is used.
- Verification: requirements installation failed at pinned GitHub `peft` with proxy 403; this sandbox lacks normal runtime packages, so the E2E selection fails collection on missing `pandas`. The blocker is recorded in `known_issues.md`.

### 2026-09-20 PR #185 corrective — offline/live layers and safety

- Added all five marker contracts, strict live opt-in and namespace validation, UUID-owned SQL/ES cleanup, live LLM/SQL/ES/composite selections, deterministic keyed fake-HTTP failure injection, retry coverage, derived-capacity-8 policy coverage, and separated focused/offline/live CI steps.
- Added `requirements-e2e.txt` without training-stack dependencies. Installation remains blocked by the sandbox package-index proxy; live selections cleanly skip without opt-in and live safety tests pass.
- No PR F work-unit, manifest, reducer, or distributed-budget functionality was introduced.

### 2026-09-20 PR #185 final production E2E corrective

- Wired an isolated Linux offline-E2E CI job to install `requirements-e2e.txt`, collect the E2E selection, and execute it independently of the Git-pinned training stack.
- Added production TXT handler, SQLite/ES `handle_data_mode`, budgeted production leaf dispatch at capacities 2 and derived 8, shared concurrent dispatch, and D2 localhost checkpoint/resume/invalidation coverage.
- Hardened live SQL cleanup, added ES CA/verification support, and accurately classified direct live SQL/ES and composite checks as service/cross-service smokes.
- No PR F functionality was introduced.

### 2026-09-20 PR #185 hosted dependency convergence corrective

- Hosted run `35515118358` proved the isolated E2E install step and exposed collection-time `psutil`; the minimal E2E surface now includes `psutil`, `version_parser`, and the other direct packaged imports reached through `utils.utilities`/`MP_utils` (`GPUtil`, `humanize`, `python-dateutil`, `scipy`, `setproctitle`).
- The isolated CI commands now scope collection and execution to `tests/e2e`, preventing unrelated repository tests from expanding the E2E dependency contract. Production-path E2E tests were not weakened or replaced.

### 2026-09-20 PR #185 stale ES helper import corrective

- Repository-wide call-site search found no invocation or re-export of `get_es_client` or `apply_es_mapping`; only stale imports existed in active `steps_es.py` and the unused `steps_es_noeventids.py` variant. Historical commit `4d9f8d5` already constructed `ElasticsearchAdapter(...).connect()` and invoked `adapter.apply_mapping_file(...)` without calling either imported helper.
- Removed both stale imports. Added focused regressions for connection configuration propagation through `resolve_es_connection()` → `ElasticsearchAdapter.connect()` and configured JSON mapping application through `ensure_schemas_es()` → `adapter.apply_mapping_file()` → `indices.put_mapping()`, including preservation of output/meta fallback mapping.
- No E2E acceptance test or ES connection/mapping behavior was weakened, and no PR F functionality was introduced.

### 2026-09-20 PR #185 headless countdown hardening

- Hardened the shared `utils.utilities.countdown_pause()` CLI boundary: zero/negative durations, absent or non-TTY stdin, unsupported `fileno()`, and unsupported non-Windows `select` now return immediately without sleeping or failing row scheduling; selectable interactive terminals retain countdown and Enter-to-skip behavior.
- Added focused regressions for absent, non-TTY, pseudofile stdin and the existing zero-second contract. Accepted TXT/SQL/ES, budget, D2, retry, and ES adapter/mapping tests remain unchanged.

### 2026-09-20 PR #185 ES value-boundary diagnostics

- Hosted run `35521017153` proved both ES row identities traverse selection, scheduling, localhost HTTP, combine, and ESSink writeback; the remaining failure is value fidelity rather than identity or mapping.
- Added ordered diagnostics without production changes: expected PK/value mapping, fake HTTP assistant content, production combined artifacts, deep-copied ESSink bulk actions, and final in-memory ES values. Each layer now asserts the same exact mapping and reports its actual mapping at the first divergence.
- The countdown, scheduler, combiner, ESSink, fake response rules, and fake ES merge behavior remain unchanged; `/cache` backup remains a separate non-fatal follow-up. No PR F functionality was introduced.

### 2026-09-21 PR #185 prepared-text E2E contract correction

- Hosted diagnostic run `35559731083` localized ES value divergence to the established text combine boundary: raw `RESULT::<pk>` becomes prepared `RESULT::<pk>\n`; identity and raw LLM response contracts passed.
- Corrected only production-orchestration test expectations: ES retains separate exact raw-LLM and combined/bulk/stored mappings, while SQL writeback expects the same prepared trailing newline. No actual value is stripped or normalized, and permanent boundary diagnostics remain.
- Classified the finding as a test-contract mismatch, not a production defect. The production combiner/reducer, Row Merger, sinks, fake services, countdown, and all PR A-E behavior remain unchanged; no PR F functionality was introduced.

### 2026-09-21 PR #185 hierarchical cleanup ownership corrective

- Hosted run `35616315448` exposed that successful production combine cleanup deleted D2 runtime and committed checkpoints under the item workspace, preventing terminal resume with `debug=False`.
- Updated only the cleanup predicate so enabled `fixed_rounds`/`adaptive_hierarchical` workspaces survive; inactive and `single_pass` debug-false cleanup remains historical.
- Added focused debug-false characterization proving initial Success, runtime, checkpoints, and terminal resume survive without a second map call, plus a single-pass cleanup non-regression. No checkpoint semantics, location, fingerprint, PR L retention policy, or PR F functionality changed.

### 2026-09-21 PR #185 deterministic ExecutionBudget E2E assertions

- Hosted run `35620840169` showed derived capacity and requested leaf width were both 8 while localhost HTTP overlap peaked at 2 because pre-HTTP endpoint load-lock work can stagger workers.
- Corrected only E2E assertions: production capacity-2 now requires snapshot `(capacity=2, peak_in_use=2, in_use=0)`; derived/shared capacity-8 requires `(8, 8, 0)` after the first and concurrent phases. HTTP concurrency remains an upper-bound safety assertion only.
- Removed the timing-dependent HTTP lower bound without changing server delay or any production budget, dispatch, pool, load-balancing, D2, or PR F behavior.

### 2026-09-22 PR #185 SQL resolver seam correction

- Hosted run `35626496688` exposed an E2E fixture defect: replacing `handle_data_mode.resolve_connection` bypassed production initialization of `sql_table`, `primary_key`, `target_table`, `sqlite_path`, and `sql_connection_string`.
- Narrowed the seam to `sql_steps.load_sql_cfg` and the `sql_steps.SQLiteAdapter` constructor factory. The real imported `resolve_connection()` now performs SQLite detection, context initialization, adapter construction, and connection entry while the recording subclass still observes selected PKs.
- Removed manual SQLite context setup from the test and added stable post-resolution assertions. No SQL production, scheduler, sink, pending-recheck, budget, D2, or PR F behavior changed.

### 2026-09-24 PR #185 TXT cleanup-contract correction

- Hosted run `35724737347` showed the production TXT lifecycle completed through localhost HTTP, Success, combine, and the final artifact; the remaining assertion incorrectly expected the non-hierarchical debug-false item workspace to survive normal cleanup.
- Added an observation-only `MergeOps.combine` wrapper that records empty TODO and populated Success state immediately before delegating unchanged to the real `combine_api_finished_item()` implementation.
- The E2E now explicitly uses `debug=False` and requires the final artifact, source backup/removal, released execution budget, and deleted temporary item workspace. No production cleanup, combine, TXT, D2, or PR F behavior changed.
