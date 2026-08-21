# Project Memory

## Current Summary

- 本專案是 Python 多來源資料處理與 LLM 多階段分析框架，核心包含資料讀取、prompt/task 設定、多階段 pipeline、LLM 呼叫、結果合併、JSON flatten 與匯出。
- SQL / Table / ES stream 多階段會在 scheduler 階段重用 `process_prompt_and_merge()` 產生 stage merge / manifest，再由 row_merger 寫回。
- 舊單階段 legacy consumer 仍使用 TODO/RUNNING/Success 佇列與 `run_round()` multiprocessing；新版明確 stage flow 會走 stage-managed / scheduler path。
- LLM call audit 會在每次 `czjLLM_TextProcessing` 啟動時建立 CSV/XLSX，token usage 來源為 LLM API response usage，context 使用率優先使用 Ollama `/api/ps` active context。
- requirements 安裝在目前環境仍受 GitHub `peft` dependency proxy 403 限制，需用 compileall、靜態檢查與可收集的目標 pytest 作替代驗證。

## Recent Changes

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

## 2026-07-28 utilities_path invalid escape warning cleanup

- 任務目的：依使用者要求保留 `clean_path_end_chars_OLD_2` 舊程式碼字串，同時消除其中 `\)` 無效跳脫造成的 Python `SyntaxWarning`。
- 主要修改內容：將包住舊程式碼的三引號字串改為 raw string，未變更目前啟用的 path utility 行為。
- 驗證結果：依規範執行 pip upgrade 與 requirements 安裝，但 GitHub `peft` clone 仍受 proxy 403 限制；替代驗證 `python -Werror -m py_compile utils/utilities_path.py` 通過。全套 pytest collect 仍因缺少 `tqdm` 停止，並保留缺少 `pytest-dotenv` 所造成的既有 `env_files` 警告。
- 重要結論：原本的 `\)` `SyntaxWarning` 已消除；變更只影響未執行的舊程式碼保存字串如何被 Python parser 解讀。

## 2026-07-20 txt single-stage LLM IO debug flags

- 任務目的：釐清並修正 txt 模式單階段 YAML 頂層 `debug_print_llm_io` / `debug_print_max_chars` 未印出 LLM I/O 的問題。
- 主要修改內容：`czjLLM/czjLLM_TextProcessing.py` 會把 YAML 頂層 debug flags 載入 `ctx`；`LLMJobConfig` 新增同名預設值；`process_prompt_and_merge()` 的 legacy single-stage 路徑在兩輪 LLM call 時會把 `ctx.debug_print_llm_io` / `ctx.debug_print_max_chars` 傳入 `call_llm_api()`，多階段仍維持各 stage 設定可覆寫。
- 驗證結果：依規範先執行 requirements 安裝，但 GitHub `peft` dependency clone 仍受 proxy 403 限制；替代驗證 `python -m compileall czjLLM/prompt_pipeline/pipeline_controller.py czjLLM/job_manager/job_config.py czjLLM/czjLLM_TextProcessing.py tests/prompt_pipeline/test_process_prompt_and_merge_di.py` 通過。嘗試執行 `python -m pytest tests/prompt_pipeline/test_process_prompt_and_merge_di.py -q` 時，因目前環境缺少 `tqdm` 且 requirements 安裝失敗而在 collection 階段失敗。
- 重要結論：使用者提供的 YAML 寫法本身可視為合理；原程式只有多階段 stage path 會讀取該 debug 設定，單階段 legacy path 未轉傳，現已補齊。

## 2026-07-20 per-run LLM call audit summary

- 任務目的：針對每次 `python -m czjLLM.czjLLM_TextProcessing` 啟動後的每一次 LLM 呼叫，產生可追溯的記錄總表，包含 task、輸入/輸出 tokens、模型、模型 context 限制、context 使用比例與是否耗盡。
- 主要修改內容：新增 `czjLLM/utilities/llm_call_audit.py`，啟動時建立 `logs/llm_call_audit/llm_call_audit_<timestamp-pid>.csv` 與 `latest_llm_call_audit.csv` 指標；`PromptAPIPipeline` 每次呼叫成功或失敗都追加一筆 CSV row，context 限制優先取 `model_spec.num_ctx`，否則由模型名稱中的 `ctx-<N>k` 推估。
- 驗證結果：依規範先執行 `python -m pip install --upgrade pip && python -m pip install -r requirements.txt`，仍因 GitHub `peft` dependency proxy 403 失敗；替代驗證包含 `python -m compileall czjLLM/utilities/llm_call_audit.py czjLLM/czjLLM_TextProcessing.py czjLLM/job_manager/job_config.py czjLLM/prompt_pipeline/pipeline_controller.py` 通過，以及以 `importlib.util.spec_from_file_location` 直接載入 `llm_call_audit.py` 的 CSV 寫入/欄位檢查通過。
- 重要結論：此功能不改 LLM prompt、輸出內容或寫回資料格式；只新增每次啟動的 audit CSV。若目前執行環境無法完整安裝依賴，仍可用 helper 純函式與 compileall 做替代驗證。

## 2026-07-20 LLM audit context source correction

- 任務目的：回應使用者指出「由模型名稱推估 context」不穩定，並詢問 token log 是否來自 API 回傳、是否可在同一呼叫流程取得 context。
- 主要修改內容：移除 `llm_call_audit` 由模型名稱 `ctx-<N>k` 推估 context 的邏輯；改為優先讀取 response extension（若端點有回傳）、再於呼叫流程中對 Ollama native `/api/show` 查詢模型 metadata（例如 `model_info.*context_length`），最後才使用明確的本地 `model_spec.num_ctx` 等設定。CSV 新增 `context_limit_source` 欄位；`CallLLMAPI` 終端 log 也會印出 context limit 與來源或 unknown。
- 驗證結果：requirements 安裝仍因 GitHub `peft` dependency proxy 403 失敗；替代驗證包含 `python -m compileall czjLLM/utilities/llm_call_audit.py czjLLM/prompt_pipeline/llm_caller.py czjLLM/prompt_pipeline/pipeline_controller.py czjLLM/czjLLM_TextProcessing.py czjLLM/job_manager/job_config.py` 通過，以及以 monkey-patched `urlopen` 模擬 Ollama `/api/show` 回傳 `gpt-oss.context_length=32768` 的 CSV 寫入檢查通過，並驗證 `name-ctx-99k` 不再被名稱解析成 context。
- 重要結論：`Tokens In/Out` 仍來自 OpenAI-compatible chat completion response 的 `usage`；context window 通常不在同一個 chat completion response 內，因此現在改在同次 LLM 呼叫完成後就近查詢模型 metadata endpoint，查不到時標記 unknown，不再以模型名稱猜測。

## 2026-07-20 terminal LLM context percentage display

- 任務目的：依使用者要求，在既有終端訊息 `Tokens In/Out ... Total` 後面直接串接 Context 使用百分比，方便批次執行時即時觀察 context 使用率。
- 主要修改內容：`CallLLMAPI()` 的 token log line 改為在可取得 context limit 時印出 `Context: <percent>% (<total>/<limit>, <source>)`；若 context metadata 無法取得則印出 `Context: unknown`，避免用模型名稱猜測。
- 驗證結果：requirements 安裝仍因 GitHub `peft` dependency proxy 403 失敗；替代驗證包含 `python -m compileall czjLLM/prompt_pipeline/llm_caller.py` 通過，以及靜態檢查確認 `Context: {context_pct:.2f}%`、`({total_tks}/{context_limit}, {context_source})` 與 `Context: unknown` log format 存在，舊 `context_line` 已移除。
- 重要結論：終端訊息現在會在 token total 同一行直接顯示 context 使用率；audit CSV 的 context 來源與百分比邏輯維持不變。

## 2026-07-20 LLM audit Excel export

- 任務目的：依使用者要求，LLM call audit 結果除了 CSV，也同步保存 Excel `.xlsx` 格式。
- 主要修改內容：`create_llm_call_audit_run()` 會同時建立 `llm_call_audit_<timestamp-pid>.csv` 與 `.xlsx`，並維護 `latest_llm_call_audit.csv` / `latest_llm_call_audit.xlsx` 指標；每次 `log_llm_call()` append CSV 後會以目前 CSV 內容重寫同名 `.xlsx`。為避免增加新的 runtime dependency，Excel 檔採用標準函式庫產生最小 OpenXML workbook，不依賴 openpyxl。
- 驗證結果：requirements 安裝仍因 GitHub `peft` dependency proxy 403 失敗；替代驗證包含 `python -m compileall czjLLM/utilities/llm_call_audit.py czjLLM/job_manager/job_config.py` 通過，以及以 `zipfile` 檢查產生的 `.xlsx` 包含 `xl/worksheets/sheet1.xml` 且 sheet XML 內含測試 task 值。
- 重要結論：audit CSV 仍是 append source of truth；`.xlsx` 是同步衍生檔，方便操作人員用 Excel 開啟檢視。

## 2026-07-20 Ollama active context source correction

- 任務目的：使用者指出 `ollama ps` 顯示 gpt-oss active `CONTEXT=36000`，但終端 log 使用 `/api/show` model max context 131072，導致 context 使用率顯示過低。
- 主要修改內容：`resolve_context_limit()` 改為使用 Ollama `/api/ps` 查詢目前已載入模型的 active context metadata，source 標記為 `ollama_api_ps`；不再使用 `/api/show` 的 model capability 作為 context 使用率分母。若 `/api/ps` 找不到 active context，才 fallback 明確 `model_spec`，否則 unknown。
- 驗證結果：requirements 安裝仍因 GitHub `peft` dependency proxy 403 失敗；替代驗證包含 `python -m compileall czjLLM/utilities/llm_call_audit.py czjLLM/prompt_pipeline/llm_caller.py` 通過，以及以 monkey-patched `urlopen` 模擬 `/api/ps` 回傳 `context_length=36000` 時，`resolve_context_limit()` 回傳 `(36000, "ollama_api_ps")`。
- 重要結論：對 truncation risk / context 使用率來說，應使用 active runtime context（等同 `ollama ps` CONTEXT 欄），不要用 `/api/show` 最大能力值。

## 2026-07-20 audit max_tokens clarification

- 任務目的：回應使用者詢問 `context_limit_tokens=36000` 但 `max_tokens=16384` 是否正常，以及 `max_tokens` 是否為輸出最大長度。
- 主要修改內容：保留相容欄位 `max_tokens`，並新增更明確的 audit 欄位 `max_output_tokens`、`context_remaining_tokens`、`effective_output_token_budget`。`max_output_tokens` 代表本次 LLM call 傳給 API 的最大 completion/output token cap；`effective_output_token_budget` 代表考慮 context 剩餘空間後的有效輸出上限。
- 驗證結果：requirements 安裝仍因 GitHub `peft` dependency proxy 403 失敗；替代驗證包含 `python -m compileall czjLLM/utilities/llm_call_audit.py` 通過，以及模擬 `input=1730`、`output=3865`、`total=5595`、`context=36000`、`max_tokens=16384` 時，CSV 欄位 `context_remaining_tokens=30405`、`max_output_tokens=16384`、`effective_output_token_budget=16384`。
- 重要結論：`num_ctx=36000` 是 input+output 共用上下文視窗；`max_tokens=16384` 是輸出上限，不是 context 上限。實際可輸出上限約為 `min(max_output_tokens, context_limit - total_tokens)`。

## Archived History

- `.codex/archive/memory-20260729-094054.md`：2026-07-29 濃縮前全文，涵蓋先前 27 筆日期工作紀錄；以 active memory 結構與保留最近 10 筆摘要完成驗證。

## 2026-08-20 ES multidim `constance` typo recovery and Row Merger log throttling

- 任務目的：釐清偶發 `Event[].constance` 導致 ES Row Merger 無限重試與終端洗版，並提供不中斷正常資料處理的窄範圍修正。
- 主要修改內容：multidim event output profile 在嚴格 schema 驗證前，將已觀察到且語意唯一的 LLM 拼字錯誤 `constance` 正規化為 `consequence`；若兩欄同時存在且內容衝突則仍拒絕寫回，避免靜默覆蓋。Row Merger 保留可修復檔案的重試語意，但相同錯誤預設最多每 60 秒提示一次，避免每 0.5 秒洗版。
- 驗證結果：requirements 安裝仍因 GitHub `peft` clone proxy 403 失敗；替代驗證 `python -m pytest tests/es_mode/test_multidim_event_field_aliases.py -q` 通過（2 passed），`python -m compileall -q czjLLM/es_mode/output_profiles/multidim_event.py czjLLM/sql_mode/runtime/row_merger_generic.py` 與 `git diff --check` 通過。
- 重要結論：問題不是新 ES mapping 隨機拒絕正常欄位，而是 LLM 偶發產生 schema 外的拼錯欄名；舊 watchdog 對確定性驗證錯誤沒有退避，因此同一完成檔每輪都重試並阻塞該列完成。此已知拼字現在可無損修復，其他未知欄位仍維持嚴格拒絕。

## 2026-08-20 preserve LLM schema failures for quality evaluation

- 任務目的：依使用者回饋撤回 `constance -> consequence` 自動修復，避免下游正規化掩蓋 LLM schema adherence 失敗並扭曲模型分析品質評估。
- 主要修改內容：multidim profile 恢復完整嚴格驗證，不再改寫 `constance`。Row Merger 將明確的 unknown-field schema 錯誤視為本輪不可恢復：記錄 `writeback_failed_schema`、釋放 pending-running 狀態、移出本輪 registry、保留來源資料且不寫回 ES；因輸出欄仍缺失，下一次執行會依既有 pending 機制重新拉取與分析。其他 ES/transport 類錯誤仍維持重試。
- 驗證結果：requirements 安裝仍因 GitHub `peft` proxy 403 失敗；現有環境也缺少 PyYAML/numpy，目標整合 pytest 在 collection 階段受阻。替代驗證以標準函式庫直接載入 multidim profile，確認 `constance` 仍拋出 unknown-field ValueError；變更檔案 compileall 與 `git diff --check` 通過。完整環境用整合測試另驗證 registry release、failure state、done signal 與來源檔保留。
- 重要結論：schema adherence failure 不應被靜默修正；跳過指的是跳過本輪 ES 寫入與 watchdog 內重試，不是把該文件標成業務完成。最終 pending recheck 仍會顯示未完成，下一次執行會重跑。

## 2026-08-20 persist and surface Row Merger schema failure evidence

- 任務目的：確定性 schema 錯誤除跳過本輪寫回外，必須明確提示操作人員並保存結構化紀錄，供後續改善 prompt、模型與 schema adherence。
- 主要修改內容：`record_adjustment()` 現在回傳實際 JSONL log 路徑；Row Merger 對 `writeback_failed_schema_release` 保存 pk、錯誤訊息、output column/profile 與 combined result artifact path，並在終端警告中直接顯示紀錄位置。running 狀態釋放與稽核寫入分開處理，避免釋放失敗連帶漏記 schema error。
- 驗證結果：requirements 安裝仍因 GitHub `peft` proxy 403 失敗；`python -m pytest tests/prompt_pipeline/test_pending_adjustment_log.py -q` 通過（1 passed），變更檔案 compileall 與 `git diff --check` 通過。
- 重要結論：schema failure 不保存原始文章或模型憑證，只保存改善分析所需的結構化錯誤 metadata 與本機 artifact 路徑；終端可直接引導操作人員找到 bounded adjustment JSONL。

## 2026-08-20 prevent credentials in ES model metadata

- 任務目的：修正 ES `<output_col>_meta.model_tag` 將完整 `model_spec` 字串化、連帶把 API key 寫入 `_source` 的安全問題。
- 主要修改內容：新增 model metadata 安全邊界，只允許 `model_name`、非敏感 `base_url_alias`、`num_ctx`、`temperature`、`model_version`；`model_tag` 若收到 dict 或 dict 字串只取 model name。ES sink 在最終寫回前遞迴移除 model_spec、實際 base URL 與 credential-like keys，並遮蔽 credential/JWT-like 字串；rerun query tag 同樣安全化。mapping 與文件新增 allowlisted 欄位。另移除 repository 內發現的硬編碼 token，改從 `CZJLLM_ANKINT_API_KEY` 讀取。
- 驗證結果：requirements 安裝仍受 GitHub `peft` proxy 403 限制；`python -m pytest tests/es_mode/test_safe_model_metadata.py tests/prompt_pipeline/test_pending_adjustment_log.py -q` 通過（4 passed），相關 Python compileall、已知 JWT 字串掃描及 `git diff --check` 通過。
- 重要結論：實際 endpoint URL 與 API credential 只供 runtime client 使用，不屬於分析結果 metadata；既有 ES `_source` 內已洩漏的 token 不會因程式更新自動消失，必須輪替並清理舊資料。
