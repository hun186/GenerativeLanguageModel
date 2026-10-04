# Project Memory

## Current Summary

- 本專案是 Python 多來源文件／表格處理與 LLM 多階段分析框架；TXT/Table/SQL/ES 共用 prompt、LLM、combine 與 writeback 基礎設施。
- `combine_api_finished_item()` 是 production 單一文件 Success slice 合併邊界；Row Merger 只負責下游協調，Output Profile 維持最終嚴格驗證。
- Reduction Engine PR A-E 已完成；PR F 已實作 immutable Logical Work Unit / Collection Manifest contract，等待 hosted offline E2E 驗證。PR G 與後續 roadmap 仍未實作。
- Hierarchical round 1 直接 reduce 原始 Success map outputs；round 2+ 才經 tokenizer、configured round task prompt、LLM map 與 concat reducer。
- Requirements 安裝在目前環境仍受 pinned GitHub `peft` proxy 403 限制；dependency-light pytest、compileall 與 diff checks 是可用替代驗證。

## Recent Changes

### 2026-09-24 Reduction Engine PR F identity safety corrective

- `logical_id` 與 `collection_id` 現在共用既有 credential-text/JWT detection，拒絕明顯 secret-bearing identity；不套用 provenance key substring 規則，因此 `secretariat-analysis-v2` 等正常 business ID 仍有效。
- Identity 穩定性仍由 caller/source adapter 的語意保證；core 不產生 object/random/PID/time identity，也不推測一般日期、數字、host/session 字樣。Provenance 則維持已知 runtime key 與 secret-bearing key/value 的結構化拒絕。
- Contract version、schema、canonical fingerprint fields/algorithm、ordering、immutability 與 reconstruction 全部不變；PR G 仍未實作。Corrected hosted-head E2E 尚待 CI 驗證。
- 驗證：focused collection tests 34 passed；完整 `tests/reduction` 175 passed；compileall 與 `git diff --check` passed。Requirements install 仍受 pinned GitHub dependency proxy 403 阻擋；corrected hosted head 的 13-case offline E2E 尚待 Actions 驗證。

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

### 2026-09-24 Reduction Engine PR G collection adapters and aggregate upsert

- Added explicit SQL and Elasticsearch collection snapshot adapters. SQL keys use type-tagged stable scalar identities; ES defaults to `_id`; both canonicalize member order using configured fields plus logical-ID tie-breaking, support safe source versions, deterministic grouping, and optional semantic half-open windows.
- Added strict atomic manifest save/load plus aggregate-output contract v1. Output identity hashes contract version, collection ID, manifest fingerprint, and caller output key. Dedicated SQLite and ES sinks use primary-key conflict upsert and ES `update`/`doc_as_upsert`, respectively; retrying a committed operation reuses one logical output.
- Existing Row Merger, pending-row selection, ordinary ESSink, reducers, and Output Profile behavior were not repurposed. Aggregate payloads are explicitly documented as already final/validated; PR H reducers remain unimplemented.
- Verification: focused reduction/SQL/ES collection selection passed 185 tests. Requirements installation remains blocked by the known GitHub proxy 403; broader SQL/ES collection stopped on missing numpy and offline E2E remains a hosted gate.

### 2026-09-29 PR G hosted-review corrective

- Replaced SQL string-key and ES `repr()` ordering with one typed semantic scalar key: bool, numeric (native integer/finite-float order), string, then bytes, followed by logical-ID tie-breaking. Numeric ranks 2 and 10 now remain 2, 10 under shuffled retrieval.
- Group provenance now stores caller-ordered `[{"field": ..., "value": ...}]` entries, keeping reserved-looking source names such as `created_at`, `timestamp`, and `host` out of provenance key vocabulary while preserving them in group identity.
- Custom ES member IDs now accept only type-tagged non-empty strings, integers, booleans, and finite floats. ES aggregate writes now use one scripted upsert whose Painless lineage guard rejects conflicting collection/fingerprint/output-key metadata atomically.
- Added two offline `e2e` cases for actual PR G SQL and ES production classes; the local PR G E2E file passes 2 tests. Expanded hosted collection is expected to be 15, but PR G remains pending until the corrected hosted head reports the authoritative count/result.

### 2026-09-29 PR G final ES create/update corrective

- ES scripted aggregate upsert now treats only Elasticsearch's `ctx.op == 'create'` as document creation. Every existing deterministic `_id` must contain and exactly match aggregate output ID, aggregate contract version, collection ID, manifest fingerprint, and output key before payload/provenance replacement.
- Missing, null, or incompatible existing lineage raises an aggregate-lineage conflict at the atomic update boundary; missing `aggregate_output_id` is never repaired or mistaken for creation.
- Verification: reduction 178 passed; focused SQL/ES 15 passed; focused PR G E2E 2 passed; compileall and diff check passed. Full hosted 15-case E2E remains required before PR G completion.

### 2026-09-30 Reduction Engine PR H deterministic composite reducers

- Added strict, exact, source-independent dedup/group/entity-union/rank/top-k reducers and a non-recursive sequential composite, with canonical JSON validation, mapping-only dotted paths, stable ordering rules, bounded metrics/audit, and central fresh configured construction.
- Extended strict deeply immutable single-pass configuration, normal registry discovery/aliases, focused reducer/config/registry/engine tests, and one manifest-to-composite-to-idempotent-SQLite E2E. PR G is confirmed merged/accepted; PR I/J/K/L remain unimplemented.
- Historical local verification is recorded below; PR #188 later passed all 16 hosted E2E cases and PR H is complete.
- Local verification: `tests/reduction` passed 228 tests; focused collection aggregate E2E passed 3 tests including PR H. Full E2E collection remains locally blocked by missing PyYAML after the required requirements install failed at the proxy-blocked pinned `peft` clone. Compile/diff results follow in the final task record.

### 2026-09-30 PR #188 public reducer fail-closed corrective

- Public PR H parameterized reducers now validate paths/types at construction independent of input cardinality. The config boundary reuses the same path grammar, which rejects empty and wholly whitespace dotted components without stripping them.
- Empty composite execution and direct nested composites fail explicitly in core. Internal group/rank/composite registry prototypes preserve discovery metadata but fail closed if executed unconfigured. PR I/J/K/L remain unimplemented.
- Historical local verification: `tests/reduction` 242 passed; focused collection aggregate E2E 3 passed; compileall and `git diff --check` passed. PR #188 subsequently passed all 16 hosted E2E cases and merged.

### 2026-09-30 PR #188 immutable payload compatibility corrective

- Canonical deterministic JSON now uses one recursive validate-and-normalize boundary: mappings become detached dicts, list/tuple values become detached lists, scalars remain unchanged, and invalid keys/non-finite/unsupported values raise `DeterministicReducerError`.
- PR H reducers and the production E2E now consume PR F immutable `LogicalWorkUnit.payload` values directly. Reducer outputs retain existing first-occurrence/reference behavior; Collection Manifest and Aggregate Output contracts remain version 1.
- Historical local verification: `tests/reduction` 249 passed. PR #188 subsequently passed all 16 hosted E2E cases and merged; PR I/J/K/L were not part of that corrective.

## 2026-09-30 Reduction Engine PR I semantic LLM reducer

- Added source-independent `semantic_llm` v1 (`semantic` alias), task-only config, canonical ordered envelope, strict runtime protocol, and final-step composite support. It is prohibited from hierarchical controllers and has no fallback.
- Added production adapter using task overlay, existing prompt/tokenizer/pipeline/audit stack, one-chunk fail-closed preflight, and inherited one-worker lease. Combine constructs it only for semantic configs.
- PR H merged as PR #188 and hosted head passed all 16 E2E cases. PR I remains pending hosted 17-case acceptance; PR J/K/L remain unimplemented.
- Verification: all `tests/reduction` passed locally (261 tests). Focused production E2E is present but local execution is blocked at missing `psutil` after dependency installs were denied by proxy.

- PR I is tracked by existing PR #189. Its corrected head must collect and pass all 17 hosted E2E cases before PR I is marked complete.

## 2026-09-30 PR #189 review corrective

- Decoupled prompt `think_mode` from pipeline `include_think`: the overlay still gives `PromptGenerator` the root setting, while semantic output uses `include_think=False` and strips internal think blocks. Empty semantic input now fails before runtime/model execution.
- Strengthened the existing seventeenth E2E case with a semantic-only fake-server think marker; E2E count remains 17. At that historical checkpoint PR #189 awaited corrected hosted acceptance; it later passed 17/17 and merged. PR J/K/L were not part of that corrective.
- Corrective local verification: focused semantic tests 14 passed; complete reduction suite 263 passed; compileall and `git diff --check` passed. Focused semantic E2E remains locally blocked at `PromptGenerator` import because proxy-blocked requirements installation leaves `psutil` unavailable; hosted PR #189 is the authoritative E2E gate.

## 2026-10-01 PR #189 hosted E2E assertion corrective

- Hosted head `6798df8e40275a5e9983fc94f8175377a7f44b63` run #428 (`36690681140`) collected 17 E2E cases. The semantic payload and think-cleanup assertions passed; the case then failed because it read system message index `0` instead of selecting the semantic user message.
- The test now identifies exactly one `role == "user"` message before checking deterministic Top-K content. No production code, semantic contract, E2E count, or PR J/K/L scope changed. At that historical checkpoint PR I awaited a fresh hosted 17-case pass; it later passed 17/17 and merged.
- Local corrective verification: `tests/reduction` passed 263 tests; compileall and `git diff --check` passed. Focused semantic E2E remains locally blocked before HTTP execution because proxy-blocked requirements installation leaves `psutil` unavailable; hosted isolated E2E dependencies are authoritative.

## 2026-10-01 Reduction Engine PR J structured relational reducer

- Authoritative baseline verified at PR #189 merge `ea3f8b4436000cbc201cd63da2a2db3259b4ab5b`; PR I passed hosted offline E2E 17/17 and is complete.
- Added source-independent `structured_relational` v1 (`relational`) with strict deeply immutable config, public-constructor fail-closed validation, stable two-pass per-record namespace canonicalization, exact reference rewrite, full immutable remap provenance, bounded fingerprint audit/metrics, and fail-closed post-remap integrity verification.
- Added focused coverage for malformed config/data, immutable PR F payloads, no mutation, deterministic order, multiple entity sets, no semantic consolidation, and unchanged multidimensional Output Profile compatibility. Added exactly one PR J E2E from immutable manifest payloads through reducer/profile/aggregate/SQLite idempotent retry.
- PR J stays unchecked until fresh hosted `offline-e2e` collects and passes 18 cases. Composite/hierarchical relational execution, PR K, and PR L were not implemented; PR F/G v1 and PR I behavior remain unchanged.
- Local verification after required setup attempt: `tests/reduction` 290 passed; Output Profile characterization 8 passed; focused PR J E2E 1 passed; compileall and `git diff --check` passed. Full local E2E collect/run is unavailable because blocked dependency installation leaves PyYAML absent; hosted CI must prove the expected 18/18 gate.

## 2026-10-01 PR #190 strict relational configuration corrective

- Existing PR #190 review identified three configuration-time ownership gaps on hosted head `8fd41c94fc92202f79763b621a00e0df29edc6af`: overlapping generated prefix namespaces, duplicate entity/reference endpoints, and exact entity/reference endpoint conflicts.
- The shared constructor/parser validator now rejects those invalid configurations before input-dependent execution. Disjoint prefixes and shared collections with different fields remain valid; the two-pass reducer algorithm, post-remap defense, provenance/audit/metrics, PR F/G/I contracts, and PR J scope are unchanged.
- PR J remains unchecked until a fresh corrected-head hosted `offline-e2e` run collects and passes all 18 cases. PR K/L remain unimplemented.
- Corrective local verification: focused structured-relational tests 40 passed; complete reduction suite 303 passed; unchanged Output Profile characterization 8 passed; focused PR J E2E 1 passed; compileall and `git diff --check` passed.

## 2026-10-01 Reduction Engine PR K1 executable foundation

- Authoritative baseline is PR #190 merge `673f14945a9348d462fe1152f7d53c7aba47497a`; its corrected hosted offline E2E gate passed 18/18, so PR J is complete.
- Added frozen executable/context/task-call contracts, production one-chunk TaskRuntime, public production prompt-renderer delegation, ordinary in-memory stage-pipeline adapter, local direct-only PipelineRef registry, deterministic safe fingerprints, tokenizer round preparation, strict stage config, and ordered fail-closed ReductionStage single-pass/hierarchical execution.
- K1 parent orchestration only caps thread width; leaf TaskExecutable owns the sole budget lease around `PromptAPIPipeline.proc()`. Existing stage state machine, reducers/controllers/checkpoints, PR F/G v1, PR I semantic behavior, and PR J relational behavior remain unchanged.
- K2 nesting/depth/cycle work and PR L caching/partial-success/retention remain unimplemented. Initial worker-map retry reuse is intentionally not promised.
- Verification: required dependency setup failed at pinned GitHub `peft` with proxy 403; complete dependency-light reduction suite passed 319 (including 16 focused K1 contract tests); required prompt-pipeline regression selection passed 15. The production K1 E2E is present but locally blocked by missing `tqdm`; hosted CI must collect/run the expected 19 cases.
- Publication attempt: local commit `222794fc8c1c831296b4d4e43e93d4177b9774b4` was created, but GitHub push/hosted PR/CI collection is blocked by the environment's HTTP 403 tunnel. No merge was attempted.

## 2026-10-01 PR #191 K1 correctness corrective

- Old hosted head `87428da5ec3316e08916c9bc6ca37f3579f2cc50` passed run #434 / `36830720933` with collect-only 19 and 19/19 offline E2E, but review found checkpoint-semantic and metadata-preservation gaps; that result applies only to the old head.
- Corrected effective task/callable/model/tokenizer/InputCutLen fingerprints, bound StagePipeline task-pool consistency, PipelineRef target audit retention, single-pass reducer metadata retention, construction detachment, and ReductionStageResult mapping detachment without adding K2 nesting or PR L behavior.
- Local verification: focused K1 contracts 30 passed; complete reduction suite 333 passed; required prompt-pipeline regression selection 15 passed. Requirements/E2E remain locally blocked by the recorded proxy dependency limitation; fresh hosted acceptance is pending.

## 2026-10-01 PR #191 final K1 task-pool corrective

- Head `1e12ba005faceaf67169a55e6e77bf794a2d90f6` passed CI #435 / `36891694196` with 19/19 offline E2E, but review found MappingProxy route resolution, implicit-global execution/fingerprint, and nested InputCutLen mismatches; that green run is pre-corrective evidence only.
- Corrected generic Mapping route pools, bound global fallback, shared cycle-safe nested task/InputCutLen traversal, and added a source/AST contract proving parent ReductionStage orchestration never leases leaf workers. K2 and PR L remain unimplemented.
- Local verification: focused K1 33 passed; complete reduction suite 336 passed; prompt-stage selection 16 passed. Fresh hosted 19/19 acceptance remains required.

### 2026-10-02 PR #192 K2 corrective pending

- K1 is complete: PR #191, CI #436 / `36895400626`, hosted offline E2E 19/19 PASS, merge `b74907c2b235bbace9afad4a5b9f676cb85e1748`.
- PR #192 K2 implements immutable depth/ref/cycle guards, bounded nested ReductionStage execution, and semantic fingerprints. Rejected hosted head `16487e4769e7d7fa4b1c7763c5efc25049460854`, CI #438 / `36964059859`, collected 20 E2E tests but failed the nested E2E because final rendered task prompts exceeded one configured token chunk.
- Corrective work makes initial and later-round preparation use the production final-prompt preflight, serializes calls through one checkpointed nested executable instance, and distinguishes expected LLM audit files from business writeback artifacts.
- Review also found the identical-child-run checkpoint race, the overly broad CSV/XLSX assertion, and out-of-scope `.codex` compaction; compaction was reverted and K2 state is appended narrowly.
- PR K2 and PR K remain unchecked pending fresh hosted 20/20 acceptance. PR L remains unimplemented.
- Corrective local verification: focused K2 suite 24 passed; full reduction suite 360 passed; prompt-pipeline regressions 16 passed. The focused production E2E remains locally blocked by the proxy-incomplete environment (`tqdm` missing) and requires the fresh hosted gate.

### 2026-10-02 Reduction Engine PR L1 persisted reuse/freshness/observability

- Baseline `721f596001201562d833810fe568f696fd15d112` ancestry was verified before editing. Added opt-in SQL processing identity freshness with shared discovery/recheck semantics and atomic payload+fingerprint writeback; legacy all-output-nonempty behavior is unchanged.
- Extended existing ES rerun freshness/meta with execution fingerprint while retaining cumulative model/pipeline/time/required-output rules. Added safe ProcessingIdentity and executable semantic fingerprint helper based on normalized Executable metadata.
- Added structured PendingDecision reasons, bounded payload-free JSONL recheck events, additive per-reason/rate counters, expanded final summary, throttled GUI snapshots, explicit collection processing-identity provenance, and preserved the legacy skip log.
- No member-result file cache/CachedExecutable, automatic K2 persistence, L2/L3 policy, checkpoint format, stage snapshot authority, or pending-running authority change was added.
- Required dependency installation remains blocked by the pinned GitHub `peft` tunnel 403; focused verification results are recorded in the final task report after completion.
- Verification: focused L1 tests 5 passed; pending/recheck selection 5 passed; complete reduction suite 361 passed; compileall and `git diff --check` passed. SQL suite collection is blocked by missing numpy and ES suite by missing elasticsearch after the required requirements install failed at the recorded proxy 403. Collection selection reached an existing unrelated SQL grouping expectation failure; focused L1 E2E cannot run locally with the incomplete dependency environment. Static E2E function count is 20 plus one existing parametrized variant, yielding expected hosted collect-only 21.

### 2026-10-02 PR #193 L1 corrective

- Pre-corrective hosted head `cb12323d0a98ed6bf3eae28182758db24e72f0df` passed CI #441 / `36973654548` and offline E2E 21/21 (job `110732742876`) but is not accepted.
- Corrected production auto fingerprint binding through existing Executable semantics before discovery, SQL metadata-column collision/schema ownership, fixed GUI Recheck status without periodic log spam, actual producer dispatch accounting, and ES query/recheck semantic reason consistency.
- Preserved destination authority, ProcessingIdentity/PendingDecision, atomic SQL stamping, ES rerun/meta policy, bounded structured events, legacy skip log, fail-open behavior, and all L1 scope exclusions. PR L1/L remain pending fresh hosted acceptance.
- Corrective local verification: semantic-freshness/ES/auto-identity/GUI selection 19 passed; pending/recheck selection 12 passed; complete reduction suite 365 passed; compileall and diff check passed. Required install remains proxy-blocked; full SQL stops on missing numpy, full ES on missing elasticsearch, and focused production E2E on missing PyYAML. Hosted corrective 21-case evidence is still required.

### 2026-10-03 PR #193 final L1 corrective

- Pre-final-corrective hosted head `874dbc865c46a02b5ba76caebbac05b213f94c70`, CI #442 / `37080278738`, offline job `111079056066`, collected 21 and passed, but remains unaccepted.
- Added narrow single-index ES broad-candidate/Python-postfilter mode for active required-output checks, retained optimized ordinary queries and dual-index bulk behavior, and kept no-eventids policy parity.
- Removed `ctx.task` fallback from canonical/legacy recheck job identifiers; identifiers now use bounded config basenames/simple pipeline names or `unknown`, preventing raw prompt leakage without widening decision diagnostics.
- PR L1 and PR L remain pending fresh hosted final-corrective acceptance; no L2/L3 or cache work was introduced.
- Final-corrective local verification: ES/recheck/privacy focused selection 21 passed; broader recheck selection 14 passed; full reduction suite 365 passed; compileall and `git diff --check` passed. Full `tests/es_mode` remains environment-blocked at missing `elasticsearch` after required install failed on pinned `peft` proxy 403. E2E function count remains 20 plus the established parametrized case for hosted collect total 21.

### 2026-10-04 Reduction Engine PR L2a implementation (pending hosted acceptance)

- Verified exact authoritative baseline/HEAD `21038d2678290cd32730009f552809730722aab4` and ancestry, then created `feat/reduction-partial-cancel-l2a`. Recorded accepted L1 evidence: PR #193 head `874ef7f8790d38c9c958dfdba0e5d020662da7eb`, CI #443 / `37120493902`, offline job `111195487211`, collect 21 and 21/21 PASS, merge `21038d2678290cd32730009f552809730722aab4`, verified/valid signature. PR L1 is complete.
- Added strict opt-in per-batch partial success, safe bounded member lineage, explicit result/audit/provenance/metrics, `reduction-stage-v3` semantic policy fingerprinting, and preserved ordered successful outputs/original Collection Manifest identity. Default remains fail-fast `require_all`.
- Added generic cancellation signals/context propagation, distinguishable `ExecutionCancelled`, cooperative executable/pipeline/nested/hierarchical checkpoints, and indexed bounded scheduling that stops submission, drains safely, and does not own leaf permits.
- PR L2 is split: L2a is core partial-success/cooperative cancellation; L2b remains the production cancellation/observability bridge. L2a remains unchecked pending fresh hosted 22-case acceptance and must not be marked complete or merged without explicit approval. PR L3 remains unimplemented.
- Local verification: focused L2a unit suite 16 passed; complete `tests/reduction` passed; required prompt-pipeline selection 16 passed; collection/aggregate selection 40 passed. The required install is proxy-blocked and new production E2E is locally blocked by missing `tqdm`; hosted CI must provide collect 22 and 22/22 full E2E evidence. Compileall/diff checks are recorded after final verification.
- Final local verification: focused L2a 16 passed; full reduction suite 381 passed; prompt regressions 16 passed; collection/aggregate regressions 40 passed; compileall and diff check passed. New L2a E2E execution is environment-blocked before HTTP by missing `tqdm`; complete E2E collect-only is blocked by missing PyYAML after the required proxy-blocked install.
