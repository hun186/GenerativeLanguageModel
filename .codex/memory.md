# GenerativeLanguageModel — Active Project Memory

## Current Summary
- **2026-11-18 #293/#294 shared NDJSON strict-reader PR (PENDING):** Local read-only `audit_multidim_event_time` and `audit_multidim_profile_offline` now reject duplicate JSON object keys at any nesting level and non-standard NaN/Infinity constants; default Python decoder otherwise silently retained last duplicate key and could report a misleading valid output. Synthetic tests cover both audits, redacted UNAVAILABLE and unchanged input. No production ES/LLM/YAML changes, Hosted CI and Codex Review pending.
- **2026-11-18 #335 new owner design (PENDING latest-head gates):** Qualitative inspection only: Windows Worker → private bounded IPC (8 pending) → GUI-process RAM ring (latest 50, 16 MiB total, 512 KiB/pair, 80k chars/side); Linux/headless retains only existing metadata Quality Log. Plaintext disk now opt-in via CZJLLM_JSON_REPAIR_CAPTURE=1; default unset/off never creates new raw files, old expired snapshots still maintained. GUI separate spawn process; no extra LLM/ES/Queue changes. Hosted CI/Codex Review of redesigned HEAD still required; do NOT merge until completed and safety/privacy review.
- **2026-11-18 #313 identity-scope disposable CAS test PR (PENDING):** A single local SQLite fixture isolates five HMAC-scoped identities differing in source document, output column, verified pipeline SHA or quality rule. Exhausting two failed repairs for one identity must not block any other after reopen/restart; an in-flight claim for another remains independent. Full source IDs and secret are not persisted verbatim. Existing Linux/Hosted Windows CAS suite should verify; no runtime ES/Worker/LLM replay, authenticated caller, cross-host or power-loss guarantee.
- **2026-11-18 PR #339 accepted main `14761b71384cd5ec694c92e5527873328af5f6dc` / #313:** Disposable child SQLite UPDATE-before-COMMIT exit(86) proves rollback preserves READY and zero repair count. Exact-head Hosted Linux offline E2E, Windows 3.10/3.11, changed-line secret scan and formal Codex 0 Findings PASS; queued self-hosted not counted. **Next separate PR (PENDING):** spawned child exit(87) after real COMMIT but before caller ACK checks durable claim/finalize and stale retry, same existing CI suites. Both are synthetic local proofs, NOT real ES/LLM/Queue replays, power-failure or cross-machine guarantees.
- 2026-11-17 PR #331 pending: expand early Linux CI ordering guard to cover new disposable SQLite, search-field, and Evidence-contract test steps introduced in #326/#327/#328; prevents future silent skip or omission. CI/Codex unverified on opened HEAD, no runtime changes.
- 2026-11-17 PR #329 pending: stabilize synthetic Worker heartbeat test against Hosted Linux scheduler jitter (1.5s fixture TTL, 2.25s stubbed call, assert expiry advanced and still live). Exact-head CI/Codex and physical operator behavior not yet verified. No runtime lease parameter, ES/LLM, Queue or deployment changed.
- **2026-11-16 #312 source merged:** Event-first date with empty Timeline allowed, YAML-local rerun only. Prior operator read-only 150-document sample is exploratory; `news_test` effective runtime policy, complete source/sink evidence, and explicit operator approval remain required before any live ES replay.
- **2026-11-15 main `aa4db08f9c958be4d879e9ffcc4e0d1c2c684ab4`:** PR #316 merged: read-only active Quality incident summary; fixed two Codex P2 validation/dedup findings, exact-head Hosted Linux/Windows 3.10/3.11, secret scan and Review PASS. PR #315 merged as `742e759b0723df79b17cd1e8abf7f4f56874f28e`: independent Meter/Load/Audit source roots. No live H100 root cause or Queue/ES change; Issue #302 OPEN.
- **2026-11-15 accepted PR #314:** offline stored Output Profile audit merged `add3f079112fcf387c7061dcb5a9a80047985316`; current Profile validation over saved NDJSON is not ES live effect, historical extraction accuracy or permission to rerun. Issue #294 remains OPEN.
- **2026-11-15 Draft PR #310:** raw before/after JSON opt-in privacy feature, HEAD `9acfdb2001c039eb5b74d45cb092aab31fac07e5`, latest hosted Linux/Windows/Secret/Codex zero findings, self-hosted queued. Remains DRAFT for independent security, physical NTFS ACL, consent/retention and operator acceptance. No raw JSON capture activated.
- **2026-11-15 Draft PR #312 / P0 Issue #293:** Event-first valid date + explicit `Event_Timeline=[]` and private YAML-controlled rerun, HEAD `b70b3a293ec7dda674519bfd1e4025c4e0fe0a24`; Hosted Linux, Windows 3.10/3.11, secret scan, credential regression and formal Code Review clean. Remains DRAFT until actual private effective `.py`/YAML and `news_test` read-only impact, sink evidence and explicit high-risk approval. Unknown dates can be valid. Never blanket-replay tens of thousands of documents.
- **2026-11-16 accepted main #317** (`1cc24f9b8ff1a5ba14600f8d6a131153ffc19c52`): pure offline opt-in-off Quality repair budget; two Codex P2 fixed, Hosted Linux/Windows/Secret PASS. **No durable ledger**, cross-process CAS or ES dispatch; #312 remains P0 Draft with private configuration/operator acceptance pending.
- **Operator boundary #266:** Windows physical NTFS/SMB, live H100/Ollama, real GUI/restart and SQL/ES sink ACK remain operator-deferred, NOT VERIFIED. Do not interpret Hosted Windows as physical operator approval. Do not interrupt in-flight workers or delete/replay production data.
- **2026-11-02 accepted #271–#274:** GUI #271 `e303a203657933847be4576b97fb9253fb990d7a`; audit evidence #272 `4befa0e1c29e46f614adeec8d3444df67ea4b7d1`; recorded model/IP #273 `a6720a7e636e40d1c814bdf52fc529217c829de2`; incremental GUI Audit #274 `7a7a9ba259e77b90f51737771bcc30058f231eae`, all exact-head hosted/review merged. This does not verify operator endpoints or SQL/ES durable ACK.
- **2026-11-03 accepted #276:** per-call observed model/IP metadata and GUI `0e4d719577060414f2a938c12aa19dfe6d777dc8`; observed assigned/calling/returned/failed is not authoritative provider receipt or persistence. #266 operator-deferred.
- **Earlier acceptance:** #239 `46b7c7290417421a6dc09e114f82c1066ce0179d`, hosted Linux `40513712390` SUCCESS; #240, #241, #242 accepted, #242 main `e010a5e07c45016f8f0ab4094c30bcd33825d3b5` and postmerge Linux `40623677955` SUCCESS. #231 merged.

## Active Safety and Workflow Constraints
- 2026-11-17 PR #332 review pending: two independent spawn-processes contend for disposable Quality SQLite revision; assert one durable IN_FLIGHT claim and blocked rival. Local fixture only; multi-host, real sink and operator security remain unverified, CI/Codex pending.
- ES Event date extraction may use core Event dates even when `Event_Timeline=[]`; do not manufacture Timeline entries or treat valid unknown as endless quality failure. Keep `rerun` policy in each task YAML, not connection `.py`. Private operator effective configuration is NOT readable from public CI.
- Keep Queue TODO/RUNNING/Success exclusive no-clobber, case-sensitive identity and Windows safe-handle boundaries. Worker request logs, run Quality events and LB leases are *observations*, not an authenticated logical retry family, current GPU load or sink acknowledgement.
- The existing standalone `scripts/diagnose_llm_dispatch_idle.py` only reads existing bounded private logs. `cross_source_run_identity=NOT_VERIFIED`; latest paired active Quality JSONL omits historical archives. Fixed incident counts are event counts, not distinct documents/root cause.
- Issue #313 Phase A is a pure policy/test contract, no durable claim. Do NOT integrate into live Consumer/ES pending without #293's privacy/config acceptance, persistent transactional CAS and actual operator evidence. Explicit manual force, pipeline version change and lower-level HTTP retry are separate semantics.
- Active memory remains under 200 lines / 40,000 UTF-8 bytes; historical exact text is in the immutable archive below. Archive-first compaction performed in this Phase A to avoid loss of old investigation and testing outcomes.

## Recent Changes
- 2026-11-17 PR #330 in review: correct multi-block Evidence counts so snippet rows in Event-free blocks do not mask missing Evidence in Event-bearing blocks. Synthetic privacy regressions; read-only audit only, no Output Profile/ES/Rerun changes. Exact HEAD CI/Review pending.
- 2026-11-17 PR #327 resynced onto #326: task-scoped, no-network GLM MultiDim search-field inventory for SRAF, distinguishing keyword-only vs text-template fields. Does not prove Chinese tokenization, actual news_test Mapping or reindex coverage; fresh HEAD Hosted CI and Codex Review required.
- 2026-11-17 PR #326 pending: an isolated, synthetic SQLite CAS proof for Quality retry state across restart and local competing connections (#313); no production ledger integration, scheduler, sink, ES/LLM, or operator reset authorization. CI, Codex Review and host acceptance unverified at opening.
- 2026-11-17 CI fast feedback PR (pending review): moved 5 existing synthetic MultiDim/quality checks to just after E2E dependency collection and before full production E2E; added ordering/coverage regression. All original full E2E and Windows Hosted gates retained, no live ES/LLM or production runtime change. Exact-head CI and Codex status NOT VERIFIED at PR creation.
- 2026-11-17 PR #324 source under review: MultiDim **read-only** profile/sample audit identifies Event vs Timeline dates split across distinct article blocks; one-block co-occurrence never proves `event_ids` correspondence. Synthetic tests added; no Output Profile, rerun, Mapping, SQL/ES, LLM or launch change. Hosted CI and exact-HEAD Codex review remain pending; no live acceptance.
- 2026-11-17 accepted #323 source merge: valid mixed Event/no-Event block outputs now have a dedicated aggregate classification. Latest HEAD Hosted Linux E2E, Windows 3.10/3.11, Secret Scan and clean Codex Review PASS; self-hosted Windows queued. No production ES/LLM activity.
- 2026-11-17 PR #323 pending review: pure read-only MultiDim Profile audit distinguishes all-empty Event outputs from valid mixed Event/no-Event article blocks. Added category, CLI text and offline regression coverage; no runtime Rerun change, no ES/LLM/secret access. Hosted CI, exact-head review and physical acceptance NOT YET VERIFIED at commit time; do not claim deployment or effective pending count.
- 2026-11-16 GLM MultiDim #319/#320/#321 source merged (code-only): strict task YAML opt-in for Output Profile-valid no-Event results; versioned Mapping/search-consumer contract; HTTPS CA-verified GET-only live Mapping diagnostic. Hosted Linux E2E/Windows 3.10/3.11/secret scans and latest Codex reviews passed for each; self-hosted Windows jobs were queued, not passed. No production ES, LLM or Rerun.
- 2026-11-16 PR #322 in review: new opt-in GET-only nested-candidate ES sampling, exact all-document vs nested-eligible denominators, Output Profile vs date-category aggregates, strict no-event guard comparison. Synthetic offline test suite and Hosted CI job added but final *current-head* CI outcome not yet verified; live `news_test` run **NOT PERFORMED**. Initial Codex P2 detected HTTP 200 partial-shard/timeout acceptance; amended to fail closed with regression tests. Initial Codex P1 requested this memory entry. Never estimate full-index pending counts from sample or assume source fidelity. This PR does not deploy, access ES or restart jobs.
- 2026-11-15: #316 Quality diagnostic and #315 split-run-root diagnostic merged and Issue #302 remains operator-gated.
- 2026-11-15: #314 offline stored Profile audit merged; #310/#312 remain Draft despite latest exact-head Hosted gate.
- 2026-11-15: #313 new independent offline-only immutable retry budget and tests; actual ledger, CAS and ES rollout are future work.

## Reviewed Work Awaiting CI
- 2026-11-17 PR #328 resynced after #327 merge: counts-only per-block Event to Evidence reference coverage, source-fidelity explicitly NOT proven, zero-evidence accepted; prior exact HEAD Hosted gates passed, **new HEAD CI and Codex pending**. No live ES or LLM.


## Search capability audit follow-up
- 2026-11-17 PR #333 under review: do not falsely report `index:false` text/keyword fields or unindexed text subfields as inverted-index searchable; no ES Mapping changed. Template test only; live Mapping/Chinese analyzer/SRAF queries remain unverified, exact-head CI and Codex pending.

## Archived History
- `.codex/archive/memory-pr312-pre317-20261116.md` — exact previous Draft #312 memory Git blob `5076db9fcaf7986b86104a72db7c875922df68d9`, original ES/YAML safety rationale and CI history preserved.
- `.codex/archive/memory.md-20261115-214100.md` — exact immediately preceding active memory Git blob `4470bd56dd3caaa54057f04a646e6c9fde40e4ad`; old pending-stage stories, historical Review/CI evidence and superseded handoffs are preserved.
- `.codex/archive/memory.md-20261103-134000.md` — original pre-#276 Git blob `1676ac16c18ad268d68582b10b2ab2e20f6718e7`.
- `.codex/archive/memory.md-20261102-152500.md` — original Git blob `5725c26247056df7baf8f8814d2998865461f259`.
- `.codex/archive/memory.md-20261101-234800.md` — original Git blob `53ef85bf9d6a616177e84b9f594b8ae28a1defea`.
- `.codex/archive/memory.md-20261101-103200.md` — exact precompaction historical memory.
- `.codex/archive/memory.md-20261030-103500.md` — original Git blob `8af2694365bd5202a1533a36c8b7cd4c82f22408`.
- `.codex/archive/memory.md-20261028-104900.md` — original Git blob `309b57f00fc85f0d03fd12fdb3b7bdfdaa4708d8`.
- `.codex/archive/memory.md-20261027-213700.md` — original Git blob `72e0fe6912d3c19e46b2c11de4da532e24ed61fd`.

## TLS Diagnostic Exception (2026-11-17)
- PR #334 pending: read-only GLM MultiDim Mapping and nested-only sample probes now refuse `--allow-ip-san-mismatch` for DNS hostnames. Only literal IPv4/IPv6 HTTPS origins can use that operator-controlled diagnostic exception. CA chain and certificate validity remain mandatory, no secrets are exported; synthetic CI/Codex still pending. No production ES/LLM/rerun or TLS certificate replacement.


## 2026-11-17 #310 Source Sync Handoff
- Draft PR #310 carries original/repaired JSON plaintext capture into the existing GLM GUI only when explicitly opted in; all production capture remains OFF. Accepted main #318–#334 is included in the source branch without removing its ES/SQLite/TLS/Queue CI gates. Native Windows NTFS ACL, nonsynced private folder, retention/consent and independent privacy/security review remain blocking for Merge and live use. Exact prior branch .codex architecture/backlog/known_issues/memory were archived before the accepted-main reconciliation. No actual operator private content or live GPU/ES/SQL was touched.

## 2026-11-17 — GLM Windows Consumer head-of-line blocking 修正 PR

- 根據使用者日誌，6 個 Queue RUNNING 對應實際 2 個 RUNNING 檔及
  4 個 Success，顯示 Legacy Thread round 統一 ACK 的延遲問題；
  日誌的 `combined=N` 並非合併路徑權威證據。
- Windows 單階段 Consumer 接入 #301 `run_slot_refill`；
  成功 Worker 在確認 Success 後逐筆結算 Queue Meter，
  才補入新 Claim。保留 Linux/多階段與 sink confirm 閘門。
- 新增 `test_consumer_live_slot_refill.py` 真實臨時 Queue、
  快慢 Worker 及缺少 Success 不得假 ACK regression；CI gate 已加入。
- 本紀錄為源碼變更：Hosted CI、Windows 工作站、雙 H100、實際 ES/SQL
  sink 寫回都 **尚未驗證**。不得聲稱對正在運行中的批次生效。

- 同 PR 後續審核發現正常 JSON output-limit split 會刪除父 RUNNING、
  產生兩個 TODO；新增 source-hash-bound split 驗證與 Queue Meter
  原子計數轉換，並補 `test_verified_split_parent_replaces_one_running_with_two_todo`。
  尚待 exact-head CI/Windows/H100/ES-Sink 實機驗證。

- 追加修正 `debug_snapshot` 的錯誤合併路徑猜測：僅對 Registry
  明確提供的 `CombBackFN` 顯示 Y/N，其他 UNKNOWN；加入單元驗證。
  源碼 PR 仍是 Draft，CI/實機驗收未完成。

## 2026-11-17 — project-local JSON repair cache follow-up
- Historical #335 source had default-on protected project-local 72h plaintext capture; **2026-11-18 owner superseded this design**. New HEAD uses GUI-only session RAM latest 50; disk now explicit opt-in only, and Linux headless doesn't capture raw. Original secure disk ACL/prune code remains optional, not default. Latest-head Hosted Linux/Windows/Codex and physical GUI remain separate gates.

## 2026-11-18 #335 CI memory-size corrective (source-only)
- **2026-11-18 #335 Codex P2 corrections (PENDING latest-head verification):** Load existing private `.env`/`.env.local` overrides using the same `load_czjllm_env_files_once` project root before a headless startup sweep; move opted-out `Path.exists()` into fixed-code `OSError` exception boundary so inaccessible optional cache does not abort an LLM batch. Synthetic tests cover selected custom-root 72h cleanup and permission-denied opt-out. Prior HEAD `f357e29f...` Hosted Linux/Windows/secret/credential PASS but Codex found two P2; no unearned claims of rereview or physical privacy authorization.
- **P2 follow-up (Codex latest-head review):** protect the new exact pre-trim contract archive with an explicit `.gitattributes -text` entry and SHA-verified regression (`c9ad2666df327abf3e3a285d1ff5f83bca1e32c8`) so Windows `core.autocrlf=true` cannot silently change historical bytes. **Fresh latest-head Hosted CI/Codex rereview still pending**, no physical Windows/privacy approval or merge.
- Archived the exact 40,510-byte pre-compaction API contract at `.codex/archive/api_contract.md-20261118-0918.md` and shortened repeated historical language, leaving 39,306 UTF-8 bytes / 200 nonempty lines with key active ES/LLM safety contracts retained. Prior Hosted Linux `offline-e2e` failed `tests/test_codex_memory_archive.py` on the 40,000-byte cap. **New HEAD CI and formal Codex rereview pending**; #335 is unmerged and still requires independent operator privacy/Windows/Linux real-host validation before plaintext default-on activation.
