# Project Memory

## Current Summary

- 本專案是 Python 多來源資料處理與 LLM 多階段分析框架，核心包含資料讀取、prompt/task 設定、多階段 pipeline、LLM 呼叫、結果合併、JSON flatten 與匯出。
- SQL / Table / ES stream 多階段會在 scheduler 階段重用 `process_prompt_and_merge()` 產生 stage merge / manifest，再由 row_merger 寫回。
- 舊單階段 legacy consumer 仍使用 TODO/RUNNING/Success 佇列與 `run_round()` multiprocessing；新版明確 stage flow 會走 stage-managed / scheduler path。
- LLM call audit 會在每次 `czjLLM_TextProcessing` 啟動時建立 CSV/XLSX，token usage 來源為 LLM API response usage，context 使用率優先使用 Ollama `/api/ps` active context。
- requirements 安裝在目前環境仍受 GitHub `peft` dependency proxy 403 限制，需用 compileall、靜態檢查與可收集的目標 pytest 作替代驗證。

## 2026-09-19 Reduction Engine PR B foundation

- 任務目的：建立尚未接入 production routing 的 source-agnostic reducer contract、獨立 registry，以及 text concat、JSON-list concat、legacy JSON deep merge adapters。
- 主要修改內容：新增 `czjLLM/reduction/` 的 `Reducer` / `ReducerResult`、builtin registry 與三個 reducer；deep merge 直接委派 `utilities.slice_merge.merge_dict_slices_audited()`，並明確保留 conflict/dedup 選項。`utilities/__init__.py` 改從 focused `slice_merge` re-export 同一函式，避免載入 reducer 時連帶要求 filesystem/OpenCC orchestration dependency。
- 驗證結果：`tests/reduction` 19 passed；PR A combine/slice-merge/output-profile characterization 29 passed；compileall、`git diff --check`、production import/static scope search 通過。multistage/Row Merger tests 因缺少 PyYAML 無法 collection；requirements 安裝仍因 GitHub `peft` proxy 403 失敗。
- 重要結論：PR B 只建立 inactive reducer socket；production combine、Row Merger、Output Profile 與 YAML routing 均未接入新 registry，opt-in routing 留待 PR C。

## 2026-09-19 Reduction Engine PR B import verification corrective

- 任務目的：明確驗證 `czjLLM.utilities` 的 focused re-export 不會破壞 public `merge_dict_slices` identity，且匯入新 Reduction package 不會載入 heavy `combine_utils` orchestration。
- 主要修改內容：新增隔離 subprocess regression test；repository-wide import inspection 確認 production callers 皆直接 import `czjLLM.utilities.combine_utils`，沒有 production module 仰賴 package import 的隱含 side effect。
- 驗證結果：Reduction tests 20 passed、PR A characterization 29 passed、compileall/diff/import-routing checks 通過。單獨安裝 PyYAML 仍因 package index proxy 403 失敗，因此 multistage/Row Merger suite 仍在缺少 `yaml` 時 collection 失敗。
- 重要結論：`czjLLM/utilities/__init__.py` compatibility concern 已由 identity 與 clean-interpreter module-load assertions 覆蓋；未發現 P1 regression。

## 2026-08-21 model-profile-driven parallelism follow-up

- 任務目的：避免為每份 ES YAML 增加 row/slice 併行參數，將預設自動政策與手動調整收旂到 model profile。
- 主要修改內容：`initialize_config()` 現在優先採用 model spec 的 `n_process` / 現有 `nProcess`，未指定才依 endpoint/GPU 規則自動計算；slice worker 優先序改為任務 override、model profile `slice_parallelism`、`ctx.n_process`。YAML 仍可 override 但不再建議為必填。
- 驗證結果：目標 parallelism pytest 通過，compileall 與 diff check 通過；requirements 安裝仍因 GitHub `peft` CONNECT tunnel 403 失敗。
- 重要結論：現有 ANKInt model profile 的 `nProcess` 以前在 `initialize_config()` 會被自動計算值覆蓋，現已成為真正生效的模型層調校值；新設定建議用 snake_case。

## 2026-08-21 independent prompt-slice tail parallelism

- 任務目的：解決 ES 批次尾端只剩一份超長 doc 時，doc-level worker 已空閒但切片並行度無法獨立調整的算力浪費。
- 主要修改內容：新增獨立 `multistage_slice_parallelism` / `llm_slice_parallelism` / `slice_parallelism` 解析，每批 prompt slice 依可用 job 數限制 worker，並輸出實際 jobs/workers 診斷。未設定時保留 `ctx.n_process` 原行為。新增 ES/SQL/table/TXT 共用路徑與單 job stage barrier 說明。
- 驗證結果：`tests/prompt_pipeline/test_dispatch_parallelism.py` 4 passed；變更 Python compileall 與 `git diff --check` 通過。requirements 安裝仍因 GitHub `peft` CONNECT tunnel 403 失敗。
- 重要結論：doc-level 與 slice-level 併行度必須分開；若後續 stage 本質上只有一個合併 prompt，則 worker 設定無法將單次 LLM call 再拆到多張 GPU。

## 2026-08-21 migrate legacy ES timeline rerun checks

- 任務目的：將仍沿用舊 `Event_Timeline.date_iso` 契約的 ES YAML 與對應 `config_es` runtime 設定同步到現行 timeline schema。
- 主要修改內容：3 份活躍 ES YAML 與 5 份對應 ES Python 設定的 `required_output_checks` 改查 `Event_Timeline.time_iso`，日期格式由只接受純日期的 `yyyy-MM-dd` 改為符合目前輸出 timestamp 的 `iso8601`；歷史備份、舊 no-event-ids schema 與 Kibana 歷史診斷不改寫。
- 驗證結果：以 Python AST 驗證 5 份 Python 設定可解析且 rerun check 均為 `time_iso` + `iso8601`；以 Ruby YAML parser 解析並驗證 3 份 YAML 的 check 組合；實際 helper 驗證 ISO timestamp 可通過；changed Python compileall、stale active-config 搜尋與 diff check 通過。目前 Python 環境仍缺 PyYAML，與既有 dependency install 限制相同。
- 重要結論：必要欄位檢查必須與目前 `InfoExtraction-MultiDim-mapping.yaml` 的 `Event_Timeline.time_iso` 及 `strict_date_optional_time||yyyy-MM-dd` 契約同步，否則成功寫回的文件仍會永久被判定 pending。

## 2026-08-21 ES rerun required-output diagnosis

- 任務目的：釐清已有多維事件輸出與最新 processing meta 的 ES 文件為何仍在每輪全部重跑。
- 主要結論：生效的 `required_output_checks` 檢查 `Event_Timeline.date_iso`，但目前多維事件輸出契約與實際文件使用 `Event_Timeline.time_iso`；因此收集不到任何值，`min_valid_count=1` 永遠不成立，freshness 判斷每次都回傳 false。即使改成 `time_iso`，現有值是 ISO 8601 timestamp，仍不可搭配只接受純 `yyyy-MM-dd` 的 validator format，應使用 `iso8601` / `strict_date_optional_time`。`force_reason` 是 sink 依「有哪些 rerun 選項被設定」產生的摘要，不代表該文件本次實際命中了列出的每個原因。
- 驗證結果：以純函式檢查確認 dotted-path collector 對範例 shape 的 `date_iso` 回傳空集合、對 `time_iso` 能取值；日期 validator 對 timestamp + `yyyy-MM-dd` 回傳 false，對 timestamp + `iso8601` 回傳 true。另以程式碼靜態核對確認 required check 失敗會直接把 output 判為不新鮮。
- 建議設定：將 check path 改成 `Event_Timeline.time_iso` 並將 format 改成 `iso8601`；若不是每篇文章都保證存在絕對時間，則移除該 required check，避免無可正規化時間的合法文章永久 pending。

## 2026-08-20 apply slice merge to authoritative writeback payload

- 任務目的：追查大量 scalar conflict 背後的合併是否真的寫回，而不只抑制重複 log。
- 主要修改內容：確認 Row Merger 原本只把 `merge_dict_slices_audited()` 結果交給 flatten／欄位展開，`write_map` 仍保存未合併的 slice list；現改為將 merge 結果同步回填到實際 writeback source 欄位。multidim event 依 schema 保持最外層 array、內含一筆合併後 article record；generic JSON 寫入合併後 object；不相干的其他 writeback rule 不會被覆寫。
- 驗證結果：新增 helper contract tests 與 retry sink assertion，確認 generic 寫回取得 merged object、multidim 寫回取得 `[merged object]`、其他 rule 保持原值；compileall 與 diff check 通過。完整 pytest 仍因 requirements proxy 403／缺少 PyYAML 無法 collection。
- 重要結論：這是實際 bug，不只是 log 太多。舊流程雖計算並顯示 `scalar_conflict → left`，但主欄位送進 sink 的仍是未合併 slice list，因此 log 所宣告的取捨沒有成為權威寫回值，且各 slice 會被逐筆 schema 驗證而放大 missing `Event` 等錯誤。

## 2026-08-20 Row Merger slice-conflict audit de-duplication

- 任務目的：依使用者指正，將「schema failure 收斂」與終端主要洗版來源 `[merge] scalar_conflict` 分開處理。
- 主要修改內容：Row Merger 對同一個 completed item 的多切片 merge audit 僅在第一次合併嘗試輸出；若 ES／SQL 暫時寫回失敗而 watchdog 重試，仍重新計算相同 merge 結果，但不再重印 scalar conflict、list dedup 與 merge summary。不同 item 仍各自保留第一次 audit，`merge_log_to_file` 行為不變。
- 驗證結果：新增 retry-once sink 測試，模擬第一次暫時性寫回失敗、第二次成功，斷言 merge 執行兩次但 scalar-conflict log 只出現一次；完成 compileall、去重路徑靜態斷言與 diff check。完整 pytest 仍受既有 PyYAML／requirements 安裝限制而無法 collection。
- 重要結論：多切片 scalar conflict 本身是 merge policy 正常解決左右值差異的 audit，不是 schema error；真正的洗版原因是同一 item 在寫回未完成時被 watchdog 重跑，連帶重印同一份 merge audit。前一版 schema typed failure 只處理其中「schema 拒絕導致重試」的一條路徑，本次才直接封住 merge audit 的重複輸出。

## 2026-08-20 Row Merger multidim validation washout completion

- 任務目的：核對舊版相同 ES schema 錯誤每 0.5 秒重試、重印 merge audit 與寫回錯誤的洗版問題，並確認使用者提供的 missing `Event`、month precision 錯誤也被涵蓋。
- 主要修改內容：output profile registry 將 transformer 的 `TypeError` / `ValueError` 統一標記為 `OutputProfileValidationError`；Row Merger 將此明確型別視為確定性 schema failure，第一次失敗即記錄稽核、釋放 running、移出本輪 registry，避免 watchdog 再次合併及印出相同內容。保留舊 unknown-field 訊息判斷供相容 sink 使用。
- 驗證結果：requirements 安裝仍因 GitHub CONNECT tunnel 403 無法取得 `peft`；目標 pytest 因缺少 PyYAML 無法 collect。替代驗證以兩個實際 payload 分別觸發 missing `Event` 與 month precision，確認 registry 均拋出 `OutputProfileValidationError`；變更檔 compileall 與 `git diff --check` 通過。
- 重要結論：先前修正只完整終止 unknown-field 類型；使用者貼出的另外兩種 validation error 仍會每分鐘提示且每次 scan 重印 merge audit。此次改成依錯誤型別判斷後，所有 output-profile schema validation failure 都會在本輪第一次失敗時收斂，但 transport/ES availability 錯誤仍保留週期重試。

## 2026-08-20 multidimensional-event ES mapping documentation sync

- 任務目的：同步 `taskSetting_Enrichment.py` 已採用的新 ES 多維事件 mapping 說明，特別是 nested `Event` 與 `event_id` / `event_ids` 關聯。
- 主要修改內容：更新 ES output profile 與多階段設定指南，說明目前 schema、時間欄位、應用層參照驗證、雙層 nested query、dynamic policy，以及既有 index 需重建/reindex 的遷移限制；舊版 `Event_Timeline.date_*` 日期正規化另標示為 legacy。
- 驗證結果：`git diff --check` 通過；以 Python 標準函式庫文字斷言核對 mapping 與文件的必要欄位、nested 型別及關聯說明通過；文件舊欄位搜尋確認僅保留於明確標示的 legacy 說明。
- 重要結論：`Event.event_id` 與各 `event_ids` 是應用層關聯，不是 ES 外鍵；mapping 保存型別，`multidim_event` profile 驗證 ID 唯一性與參照存在性，task prompt 另要求每個事件具 evidence 關聯。

## 2026-07-29 authoritative post-writeback pending recheck

- 任務目的：釐清完成進度已達 10/10 時，收尾摘要仍顯示 `仍未完成=1` 卻接著宣告完成的矛盾訊息。
- 主要修改內容：producer 保存本輪實際派工 pk；orchestrator 在 merger/writeback shutdown 完成後逐筆執行權威最終重查。原 finalize 數字改稱「running 中控清理快照」，明示可能早於最後寫回；最終仍有 pending 或 recheck error 時不再印出成功慶祝訊息，而是警告不可視為全部完成。
- 驗證結果：requirements 安裝仍因 GitHub `peft` dependency proxy 403 失敗；替代驗證 `python -m pytest tests/sql_mode/runtime/test_pending_recheck_summary.py -q`（3 passed）與 `python -m compileall -q czjLLM/sql_mode/runtime/pending_recheck.py czjLLM/sql_mode/runtime/producer.py czjLLM/sql_mode/runtime/orchestrator.py` 通過。
- 重要結論：舊 `仍未完成=1` 是 writeback 尚在進行時的協調狀態快照，不足以判定最終失敗；新摘要以 shutdown 後資料來源重查結果作完成判定。


## 2026-07-28 remove unused clean_path_end_chars_OLD_2 block

- 任務目的：依使用者後續指示確認 `clean_path_end_chars_OLD_2` 是否仍被使用，若未使用則刪除。
- 主要修改內容：全專案搜尋確認該名稱只存在於三引號舊程式碼字串與先前記憶紀錄，因此刪除整個舊程式碼字串，並移除僅由該字串提及的 `sys`、`PureWindowsPath`、`PurePosixPath` imports；目前啟用的 `clean_path_end_chars` 不變。
- 驗證結果：`python -Werror -m py_compile utils/utilities_path.py`、`python -m compileall -q utils/utilities_path.py` 與舊名稱/unused import 靜態檢查通過。`python -m pytest tests/test_paths.py -q` 因 requirements 無法完整安裝、環境缺少 `numpy` 而在 collection 階段停止；requirements 安裝仍受 GitHub `peft` proxy 403 限制。
- 重要結論：未使用的保存字串已直接移除，不再需要以 raw string 壓制警告，也減少無效 imports。

## 2026-08-26 ES mapping rejection retry-loop fix

- 任務目的：處理 ES 欄位 mapping 已是 `text`、但 LLM 結果送入 object 時的確定性 400 錯誤與終端洗版。
- 主要修改內容：ESSink 將 `document_parsing_exception` / `mapper_parsing_exception` 類 400 判定為不可重試的 schema writeback failure，從 buffer 移除已成功及永久失敗 action，只保留可重試失敗；錯誤摘要限制長度且不在 sink 重複 print。Row Merger 透過既有 `OutputProfileValidationError` 終止同一 completed item 的 watchdog 重試、釋放 running 狀態並保持資料 pending。
- 驗證結果：`tests/test_es_sink_multifield_writeback.py` 3 passed；目標 Python compileall 與 `git diff --check` 通過。含 Row Merger 的整合測試因 requirements 安裝受 GitHub proxy 403、環境缺少 PyYAML 而無法收集。
- 重要結論：此修正停止無效重試與洗版，但不會把 object 強制轉成文字或修改既有 ES mapping；資料契約仍需由 mapping 或輸出 schema 擇一校正。

## Memory Compaction 2026-08-26

- `.codex/memory.md` 因累積超過 20 個日期工作區塊而濃縮；濃縮前全文保存於 `.codex/archive/memory.md-20260826-041906.md`。
- Active memory 保留 Current Summary、最近 10 筆歷史與本次紀錄；以檔案存在、日期區塊計數及 Markdown 內容檢查驗證。

## Archived History

- `memory.md-20260826-041906.md`：2026-08-26 濃縮前完整 Project Memory。

## 2026-08-26 Event.consequence LLM quality diagnosis and pre-write validation

- 任務目的：確認 `Event.consequence` object 是否為 LLM 輸出品質問題，並補足寫回前型別防線。
- 主要修改內容：程式內 prompt/schema 明確定義 `Event.consequence` 為文字或 null；multidim output profile 現在於 ES bulk 前驗證此欄型別，Impact-like object 會成為可定位的 schema-adherence failure，不再等 ES mapping 400 才發現。
- 驗證結果：`tests/es_mode/test_multidim_event_field_types.py` 3 passed；變更 Python compileall 與 `git diff --check` 通過。requirements 安裝仍受 GitHub CONNECT tunnel 403 限制。
- 重要結論：範例 payload 把應屬 `Impact[]` 的 `{impact_description, event_ids}` object 放進文字欄 `Event.consequence`，主要是 LLM schema adherence / 欄位歸屬品質錯誤；先前 profile 僅檢查欄名與時間，未檢查 consequence 型別，屬應用端防線缺口。

## 2026-09-01 restore LLM call audit rows in legacy consumer

- 任務目的：修復任務正常完成但 `logs/llm_call_audit` CSV/XLSX 只有標題、沒有呼叫條目的回歸。
- 根本原因：啟動流程雖將 audit run id/path 存入 `ctx`，stage-managed `call_llm_api()` 也會傳入 worker，但 legacy `llm_stream_consumer()` 建立 `PromptAPIPipeline` 時遺漏這兩個欄位；`log_llm_call()` 因空 `audit_path` 直接返回。
- 主要修改：集中由 `_llm_call_audit_kwargs()` 複製每次執行的 audit metadata，legacy consumer 與 stage-managed worker factory 均使用；JSON repair 與 split retry 子呼叫也繼承相同 run/path，避免後續 LLM 呼叫脫離總表。
- 驗證結果：`tests/prompt_pipeline/test_llm_call_audit.py` 2 passed；變更檔 compileall 與 `git diff --check` 通過。requirements 安裝仍在 GitHub `peft` clone 遭 CONNECT tunnel 403，使用不依賴該套件的目標測試完成替代驗證。
- 重要結論：只建立 header 不代表 audit writer 故障；所有 multiprocessing/thread worker job 必須明確攜帶 parent context 的 audit run id/path。

## 2026-09-18 authoritative premerged multidim writeback

- 任務目的：修正多切片 JSON 已由 `combine_api_finished_item()` 合併成 dict 後，Row Merger 因只處理 `list[dict]` 而略過 multidim 最外層 array 契約的寫回失敗。
- 主要修改內容：Row Merger 現在保留每個 writeback 欄位由 `resolve_writeback_payload()` 回傳的結構化 source；僅對 `source == "combined"` 的 premerged dict 重用既有 `_apply_slice_merge_to_write_map()`／output-profile serializer。multidim 寫入 `[dict]`，generic JSON 維持 dict，`stage:*` dict 不會被此 workaround 修復，仍交由 profile validation 拒絕。上游 combine 與 scalar-conflict policy 未更動。
- Regression coverage：保留既有 list merge contract，新增 authoritative combined dict 的 Row Merger/capture sink regression、generic object contract，以及 stage-specific invalid dict 仍可被 multidim validator 拒絕的測試。
- 驗證結果：`tests/test_combine_json_slice_merge.py` 6 passed；changed Python `compileall` 與 `git diff --check` 通過。Row Merger 目標測試在 collection 階段因缺少 PyYAML 失敗；test-only PyYAML shim 後又確認缺少 OpenCC，屬 requirements 未完整安裝的環境限制而非 test assertion failure。
- 環境限制：`python -m pip install -r requirements.txt` 仍因 GitHub `peft` clone 遭 proxy `CONNECT tunnel failed, response 403` 而失敗；`pip --upgrade` 亦無法連 index，但現有 pip 已安裝。
- 記憶維護：`.codex/known_issues.md` 超過 20 個工作紀錄區塊，已依規範濃縮；完整歷史保存於 `.codex/archive/known_issues-20260918-000000.md`。

## 2026-09-19 Reduction Engine Phase 0 reconciliation

- 任務目的：將 Codex Phase 0 在隔離 checkout 中驗證的 Reduction Engine 架構 findings，合回真正 PR #177 的 authoritative plan，而不是以 reconstructed plan 取代原稿。
- 權威基線：`main @ c834959d8482e96ab3e815278aec2137952df8d7`；PR branch 起點為 `plan/reduction-engine-v1 @ eaaf89e131ed814dddc6813beb8d3839fc47b587`。
- 已確認 live combine 仍以 `combine_api_finished_item()` 為核心；`czjLLM/pipeline/merge/` 為與 live TXT/SQL/ES runtime 分離的 skeleton，不作 Reduction Engine foundation。
- 架構定案：Reduction Core 維持 source-agnostic；Row Merger 留在 SQL/table/ES writeback 邊界；Output Profile 與 Reducer Profile 分離；worker 採小型 `Executable` contract + Task/PipelineRef adapters，而不是直接依賴整個 business-stage runtime。
- 執行順序修正：Shared `ExecutionBudget` 提前成為 collection/semantic/nested fan-out 的 prerequisite；Collection Manifest 使用獨立 immutable contract；aggregate creation 使用 stable `aggregate_output_id`/idempotent upsert，而非只依賴既有 row/document update identity。
- 下一個 production-facing 工作仍是 PR A Characterization / Golden Tests，且 production behavior change = NO。

## 2026-09-19 Reduction Engine PR A characterization

- 任務目的：在導入 Reduction Engine routing 前，以 golden tests 凍結既有 combine、slice merge、multi-stage source resolution、Row Merger 與 Output Profile 邊界；production behavior change = NO。
- 已凍結行為：文字切片採 Success 路徑字典序、逐非空切片補單一換行並略過 `無主題相關內容`；JSON 只保留 list 第一層的 dict，單一 dict/list 均輸出 list envelope，多個 JSON slice 在 merge 開啟時輸出 merged dict；valid + malformed 混合時只輸出已解析 rows，而全 malformed `return json` 回退原文字串。
- Slice merge 相容陷阱：預設 `prefer_left`，空字串與 null 可由右值補入；list concat 可依 audited path 去重；type mismatch 固定保留左值。Audit tests 凍結 changed/counts/sample action/path/chosen 語意，不依賴完整 log 格式。
- Writeback 邊界：`combined` 與 `stage:<name>` 選取不同 artifact；malformed stage payload 保留為字串。既有 Row Merger regression 繼續凍結 generic combined dict、multidim combined `[dict]` wrapper、stage dict 不自動修復、retry recomputation 與 merge-audit 去重。
- Output Profile 邊界：generic profile 保持 identity pass-through；multidim profile 仍嚴格拒絕缺 Event、錯誤型別/時間精度、重複或 unresolved event ID 與 object consequence，registry 統一拋出 `OutputProfileValidationError`。
- 驗證：新增 dependency-light combine/slice/profile tests 29 passed；multi-stage source tests 7 passed（以 import-only package seam 避開缺少 optional runtime dependencies）；requirements 安裝仍因 pinned GitHub `peft` proxy CONNECT 403 失敗。

## 2026-09-19 Reduction Engine PR C opt-in single-pass routing

- 任務目的：在不改變預設 production behavior 的前提下，加入單一嚴格 `reduction` 設定邊界與三個 PR B reducer 的 explicit single-pass routing。
- 主要修改內容：新增 immutable `ReductionConfig`、`ReductionConfigError`、嚴格 parser 與 `reduce_single_pass()` facade；root YAML 對 TXT/Table/SQL/ES 共用投影至 `ctx.reduction`，combine 只在 `enabled=true` 時將既有 prepared payload 送入 reducer。`merge_slices=true` 與 explicit reduction 互斥；deep-merge combine route 明確採 `dedup_lists=true` 等 caller-level compatibility defaults。
- 驗證結果：`tests/reduction` 45 passed；PR A combine/slice-merge/output-profile characterization 29 passed；routing OFF spy 與三種 routing ON profile 均通過。Row Merger/multistage suite 因缺少 PyYAML 無法 collection；requirements 安裝仍因 pinned GitHub `peft` proxy 403 失敗。compileall、diff check 與 scope/import checks 通過。
- 重要結論：Row Merger、multistage writeback、Output Profile、`pipeline/merge` 與 legacy slice merge utility 均未改動；hierarchical/controller framework 仍留待 PR D+。
