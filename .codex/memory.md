# Project Memory

## Current Summary

- 本專案是 Python 多來源資料處理與 LLM 多階段分析框架，核心包含資料讀取、prompt/task 設定、多階段 pipeline、LLM 呼叫、結果合併、JSON flatten 與匯出。
- SQL / Table / ES stream 多階段會在 scheduler 階段重用 `process_prompt_and_merge()` 產生 stage merge / manifest，再由 row_merger 寫回。
- 舊單階段 legacy consumer 仍使用 TODO/RUNNING/Success 佇列與 `run_round()` multiprocessing；新版明確 stage flow 會走 stage-managed / scheduler path。
- LLM call audit 會在每次 `czjLLM_TextProcessing` 啟動時建立 CSV/XLSX，token usage 來源為 LLM API response usage，context 使用率優先使用 Ollama `/api/ps` active context。
- requirements 安裝在目前環境仍受 GitHub `peft` dependency proxy 403 限制，需用 compileall、靜態檢查與可收集的目標 pytest 作替代驗證。

## Recent Changes

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

## 2026-07-20 token usage source clarification

- 任務目的：回應使用者詢問 audit 的 input/output token 數是本地 tokenizer 計算或 LLM API 回傳，避免誤以為使用任意本地 tokenizer。
- 主要修改內容：audit CSV/XLSX 新增 `token_usage_source` 欄位；正常 LLM response 有 `usage` 時標記為 `llm_api_usage`，若端點未回傳 usage 則標記 `unavailable`。終端 token log 也改成 `Tokens(API) In/Out`，明確表示 token 數來自 API response usage，不是本地 tokenizer 估算。
- 驗證結果：requirements 安裝仍因 GitHub `peft` dependency proxy 403 失敗；替代驗證包含 `python -m compileall czjLLM/utilities/llm_call_audit.py czjLLM/prompt_pipeline/llm_caller.py` 通過，以及模擬 response.usage 時 CSV 欄位 `token_usage_source=llm_api_usage`。
- 重要結論：目前 audit 不使用本地 tokenizer 計算 input/output token；若相容端點沒有回傳 `usage`，token 欄位會是 0 並標記 `unavailable`，避免產生不準的本地估算。

## 2026-07-20 MP tool debug YAML switch

- 任務目的：使用者提供 `[MP-POOL-CREATE] / [MP-POOL-JOINED]` 平行化診斷訊息洗版範例，要求改為可由 YAML 控制的開關。
- 主要修改內容：`utils.MP_utils.multicoreJob` 新增 `mp_debug` 參數與 `CZJLLM_MP_DEBUG` 臨時環境變數覆寫；預設不再列印 `[MP-POOL-CREATE] / [MP-POOL-JOINED]` 診斷訊息，`czjLLM_TextProcessing` 讀取 YAML 頂層 `mp_debug` 並由 legacy LLM API 呼叫路徑傳入 `multicoreJob`。同步更新 debug 功能文件。
- 驗證結果：依規範先執行 requirements 安裝，但 GitHub `peft` dependency proxy 403 失敗；替代驗證包含 `python -m compileall utils/MP_utils.py czjLLM/prompt_pipeline/pipeline_controller.py czjLLM/czjLLM_TextProcessing.py czjLLM/job_manager/job_config.py` 通過，以及靜態 marker 檢查通過。`python -m pytest tests/prompt_pipeline/test_round_runner_smoke.py -q` 仍因既有 Windows spawn-overlap 測試預期失敗，與本次 MP tool debug 開關無直接關聯。
- 重要結論：正式批次可省略 `mp_debug` 以避免 `[MP-POOL-CREATE] / [MP-POOL-JOINED]` 洗版；需要追查 process / start method / active children / stack 時，於 YAML 設 `mp_debug: true` 或臨時設定 `CZJLLM_MP_DEBUG=1`。

## Archived History

- `memory.md-20260720-111619.md`：於 2026-07-20 11:16:19 UTC 濃縮前保存完整 `.codex/memory.md` 歷史，涵蓋 2026-06-23 至 2026-07-20 多筆任務紀錄。

## 2026-07-21 LLM audit elapsed/time rate fields

- 任務目的：依使用者要求，將終端已顯示的 LLM 呼叫「耗時」與「處理速率」同步加入 audit CSV 與 Excel 總表。
- 主要修改內容：`CallLLMAPI()` 會把每次呼叫計算出的 elapsed seconds 與 tokens/sec 附加在 response 物件上；`llm_call_audit.log_llm_call()` 新增 `elapsed_seconds` 與 `processing_tps` 欄位，CSV append 與同步產生的 `.xlsx` 都會包含這兩欄。
- 驗證結果：依規範先執行 requirements 安裝，但 GitHub `peft` dependency clone 仍受 proxy 403 限制；替代驗證包含 `python -m compileall czjLLM/utilities/llm_call_audit.py czjLLM/prompt_pipeline/llm_caller.py` 通過，以及以 `importlib.util.spec_from_file_location` 載入 audit helper，模擬 response usage 後確認 CSV 與 XLSX 皆含 `elapsed_seconds=2.50`、`processing_tps=60.00`。
- 重要結論：audit 的耗時與處理速率沿用實際 LLM API 呼叫流程內已計算並顯示於終端的數值，不改任務輸出 schema。

## 2026-07-21 SQLite pending recheck thread safety

- 任務目的：說明並修正 SQLite SQL mode 在 stream/multistage producer worker thread 內執行 pending recheck 時出現 `SQLite objects created in a thread can only be used in that same thread` 的警告。
- 主要修改內容：`SQLiteAdapter.connect()` 改用 `check_same_thread=False` 建立連線，並新增 adapter 級 `RLock` 序列化 SQLite cursor/connection 操作；`is_row_pending()`、schema helper 與 `select_pending_rows()` 改用方法內 local cursor，避免共用 cursor 被多執行緒交錯使用。
- 驗證結果：依規範先執行 requirements 安裝，但 GitHub `peft` dependency clone 仍受 proxy 403 限制；替代驗證 `python -m compileall czjLLM/sql_mode/adapters/sqlite_adapter.py tests/sql_mode/runtime/test_sqlite_adapter_threading.py` 通過，且 `python -m pytest tests/sql_mode/runtime/test_sqlite_adapter_threading.py -q` 通過，覆蓋 worker threads 呼叫 `SQLiteAdapter.is_row_pending()` 不再觸發 SQLite thread ownership 錯誤。
- 重要結論：原警告不是 LLM 失敗；程式會「保守繼續排程」所以結果仍可能完成，但會讓 pending recheck 失效，可能造成已完成列被重複派工。修正後 SQLite pending recheck 可在 producer thread pool 中正常運作。

## 2026-07-21 pending recheck fail-open clarification

- 任務目的：回應 review 對 `pending recheck` 失敗時是否「當作沒有正在做／直接略過」的疑慮。
- 主要修改內容：`still_pending_before_dispatch()` 的 exception fallback 保持 `return True`，語意是「無法確認已完成，因此視為仍待處理並繼續排程」，不是略過；同步將警告訊息改得更明確，避免誤讀成已確認沒有 running 或已完成。
- 驗證結果：requirements 安裝仍因 GitHub `peft` dependency proxy 403 失敗；替代驗證 `python -m compileall czjLLM/sql_mode/adapters/sqlite_adapter.py czjLLM/sql_mode/runtime/pending_recheck.py tests/sql_mode/runtime/test_sqlite_adapter_threading.py` 通過，`python -m pytest tests/sql_mode/runtime/test_sqlite_adapter_threading.py -q` 通過。
- 重要結論：pending recheck 是派工前確認「目標是否已完成」的 best-effort 檢查；若檢查本身失敗，系統 fail-open 以避免漏處理資料列，代價是可能重複派工。

## 2026-07-21 SQLite pending recheck independent connection

- 任務目的：回應使用者確認 SQLite thread ownership 錯誤是否會讓 pending recheck 失效並造成算力浪費；改進前一版修正，避免只靠 `check_same_thread=False` 共用連線。
- 主要修改內容：`SQLiteAdapter.connect()` 回到 SQLite 預設 thread ownership；`SQLiteAdapter.is_row_pending()` 對 file-backed SQLite 改用短生命週期 independent connection 執行 pending recheck，使 producer worker thread 不會碰到主 iterator connection。`:memory:` 測試/特殊情境保留原連線 fallback。
- 驗證結果：requirements 安裝仍因 GitHub `peft` dependency proxy 403 失敗；替代驗證 `python -m compileall czjLLM/sql_mode/adapters/sqlite_adapter.py czjLLM/sql_mode/runtime/pending_recheck.py tests/sql_mode/runtime/test_sqlite_adapter_threading.py` 通過，`python -m pytest tests/sql_mode/runtime/test_sqlite_adapter_threading.py -q` 通過。
- 重要結論：在修正前，SQLite pending recheck 因 thread ownership 例外確實會 fail-open，導致可能重複派工與算力浪費；修正後 file-backed SQLite 的 pending recheck 不再依賴跨 thread 共用連線，應可正常判斷已完成 row 並略過。

## 2026-07-21 pending recheck observability for SQLite rerun

- 任務目的：使用者提供 SQLite multistage rerun log，詢問 pending recheck 是否有發揮作用；現有 log 只顯示 recheck enabled 與 scheduled，無法直接看出每個 pk 的 recheck 結果。
- 主要修改內容：pending recheck 啟用訊息新增 target table 與 output_cols；`still_pending_before_dispatch()` 會統計 checked/pending/already_completed/errors，並預設列印前 10 筆 pending / already_completed 狀態（可用 `pending_recheck_log_first: 0` 關閉，或 `debug_pending_recheck: true` 全量列印）；producer 收尾列印 summary。
- 驗證結果：requirements 安裝仍因 GitHub `peft` dependency proxy 403 失敗；替代驗證 `python -m compileall czjLLM/sql_mode/adapters/sqlite_adapter.py czjLLM/sql_mode/runtime/pending_recheck.py czjLLM/sql_mode/runtime/producer.py tests/sql_mode/runtime/test_sqlite_adapter_threading.py` 通過，`python -m pytest tests/sql_mode/runtime/test_sqlite_adapter_threading.py -q` 通過。`python -m pytest -rs tests/sql_mode/runtime/test_producer_pending_recheck.py -q` 因目前環境缺少 PyYAML 而全檔 skip / exit code 5，屬既有限制。
- 重要結論：從使用者 log 看，沒有再出現 SQLite thread ownership error，表示前一修正避免了原本的 recheck 例外；但因未列印每列 state，無法判定是 recheck 判斷為 pending、還是初始 pending SELECT 仍選出已完成 rows。本次新增 observability 後，下次 log 可直接看 `pk=... state=already_completed` 是否命中，以及 summary 的 skipped/error 數。

## 2026-07-21 distinguish dispatch vs finalize pending recheck

- 任務目的：使用者提供 log 顯示 `pending recheck pk=... state=already_completed` 出現在多階段完成後，詢問是否真的省到算力，或只是最後才 recheck。
- 主要修改內容：將 dispatch-time pending recheck（切片/派工前，會省 LLM 算力）與 pending-running console finalize recheck（排程完成後清理中控狀態，不省算力）分開統計與列印。producer 現先列印 `pending recheck dispatch summary`，再執行 finalize cleanup，最後列印 `pending running finalize recheck summary`；finalize 預設不再輸出 per-pk `pending recheck` 行，避免誤判為省算力。
- 驗證結果：requirements 安裝仍因 GitHub `peft` dependency proxy 403 失敗；替代驗證 `python -m compileall czjLLM/sql_mode/adapters/sqlite_adapter.py czjLLM/sql_mode/runtime/pending_recheck.py czjLLM/sql_mode/runtime/producer.py tests/sql_mode/runtime/test_sqlite_adapter_threading.py` 通過，`python -m pytest tests/sql_mode/runtime/test_sqlite_adapter_threading.py -q` 通過。`python -m pytest -rs tests/sql_mode/runtime/test_producer_pending_recheck.py -q` 因缺少 PyYAML 全檔 skip / exit code 5。
- 重要結論：使用者該段 log 的前三筆 dispatch recheck 均為 `state=pending`，所以派工前沒有跳過任何 row，沒有省到主要 LLM 算力；最後出現的 `already_completed` 是 finalize cleanup 檢查，發生在多階段已完成後，不代表省算力。

## 2026-07-21 concurrent CMD pending running wait

- 任務目的：使用者同時開兩個 CMD 跑同一 SQLite multistage 任務，第二視窗雖偵測到 `pending running console enabled: defer running rows=3 after non-running rows=0`，但立刻 fallback revisit 並三列 dispatch recheck 都是 `pending`，因此仍重複跑 LLM。
- 主要修改內容：當 producer 發現所有候選 rows 都已由其他程序標記 running 時，不再立即 revisit 排程；新增 `_wait_before_revisiting_all_running_rows()`，預設最多等待 120 秒、每 1 秒輪詢 pending running console，待 running 全清後再額外等待 3 秒讓 SQLite writeback 可見，最後才 fallback revisit 並由 dispatch pending recheck 決定是否 skip。可用 `pending_running_all_deferred_wait_seconds`、`pending_running_poll_seconds`、`pending_running_clear_grace_seconds` 調整。
- 驗證結果：requirements 安裝仍因 GitHub `peft` dependency proxy 403 失敗；替代驗證 `python -m compileall czjLLM/sql_mode/adapters/sqlite_adapter.py czjLLM/sql_mode/runtime/pending_recheck.py czjLLM/sql_mode/runtime/producer.py tests/sql_mode/runtime/test_sqlite_adapter_threading.py` 通過，`python -m pytest tests/sql_mode/runtime/test_sqlite_adapter_threading.py -q` 通過。`python -m pytest -rs tests/sql_mode/runtime/test_producer_pending_recheck.py -q` 因缺少 PyYAML 全檔 skip / exit code 5。
- 重要結論：使用者兩個視窗的既有 log 中，兩邊 dispatch-time pending recheck 都是 `state=pending`，所以沒有省到主要 LLM 算力；根因是第二視窗知道 rows 正在 running，卻立即 fallback revisit。修正後第二視窗會先等待第一視窗完成/寫回，再 recheck，理論上更容易看到 dispatch `already_completed` 並節省算力。

## 2026-07-21 pending recheck final summary before completion

- 任務目的：回應使用者指出多執行緒終端輸出會讓 pending recheck 重要訊息彼此覆蓋、難以判讀，要求在 `🎉 資料處理完成！` 前加入整理摘要。
- 主要修改內容：新增 pending recheck 完成摘要 formatter / emitter，於 SQL runtime orchestrator 收尾後、完成訊息前輸出候選總列數、派工前 checked / pending / already_completed / errors、producer 實際送出列數、finalize running 清理重查統計與「pending 不是佇列卡住、already_completed 才是已完成跳過」說明；同步套用舊 `orchestrator_good_move_down.py` 收尾路徑。
- 驗證結果：依規範先執行 requirements 安裝，但 GitHub `peft` dependency clone 仍受 proxy 403 限制；替代驗證 `python -m compileall czjLLM/sql_mode/runtime/pending_recheck.py czjLLM/sql_mode/runtime/orchestrator.py czjLLM/sql_mode/orchestrator_good_move_down.py tests/sql_mode/runtime/test_pending_recheck_summary.py` 通過，且 `python -m pytest tests/sql_mode/runtime/test_pending_recheck_summary.py -q` 通過。
- 重要結論：新增摘要只讀取既有 recheck stats，不改派工、跳過、合併或寫回語意。

## 2026-07-21 ES stream TODO empty diagnostics and wait tuning

- 任務目的：回應使用者在兩個 CMD 同時跑同一個 ES 模式任務時，看到多筆 `TODO 未產生或為空`，釐清是否正常並降低共享/遠端磁碟或慢速 prompt 產生造成的誤判跳過。
- 主要修改內容：`schedule_one_row()` 現在先把空白輸入列視為明確 noop，不再混同為 TODO 產生失敗；等待 TODO 檔案出現的時間由固定 10 秒改為可設定的 `schedule_todo_wait_seconds` / `sql_schedule_todo_wait_seconds`，預設 30 秒，並在失敗訊息加入 wait、input_chars、temp_size 與 item_dir 以利判讀。
- 驗證結果：依規範先執行 `python -m pip install --upgrade pip && python -m pip install -r requirements.txt`，仍因 GitHub `peft` dependency proxy 403 失敗；替代驗證 `python -m compileall czjLLM/sql_mode/runtime/scheduler.py` 通過。嘗試執行 `python -m pytest tests/sql_mode/runtime/test_scheduler_multistage_combback_path.py -q` 時，因目前環境缺少 `yaml` 且 requirements 安裝失敗而在 collection 階段失敗。
- 重要結論：`merge check ... TODO=0, Success=0` 在 LLM 已 claim 到 RUNNING 時可短暫出現，不一定異常；但 `❌ TODO 未產生或為空` 代表 scheduler 在切片/產 prompt 後找不到可執行 prompt，不應頻繁出現，若不是空白輸入或外部檔案系統延遲，就需要追查 prompt 寫入失敗、路徑/權限或欄位內容。

## 2026-07-23 ES prefetch default disabled

- 任務目的：使用者確認在 ES YAML 加入 `es_prefetch_buffer: 0` 後，雙 CMD 同跑 ES 任務時大量 `TODO 未產生或為空` 訊息消失，要求將預設改為關閉並補充文件說明。
- 主要修改內容：`build_es_adapter_config()` 與 `build_pending_iter_es()` 的 `es_prefetch_buffer` fallback 改為 `0`；所有 `czjLLM/config_es/akconfig_es*.py` 範例設定同步改為 `es_prefetch_buffer = 0`；`czjLLM/docs/usage/es_multistage_config_guide.md` 新增 ES prefetch 設定說明、適用情境與觀察重點。
- 驗證結果：依規範先執行 `python -m pip install --upgrade pip && python -m pip install -r requirements.txt`，仍因 GitHub `peft` dependency proxy 403 失敗；替代驗證 `python -m compileall czjLLM/es_mode/entry/steps_es.py czjLLM/config_es` 通過，且靜態檢查確認 entry fallback 與 ES config 範例皆使用 `es_prefetch_buffer=0`。
- 重要結論：LLM-heavy ES 任務的瓶頸通常是 LLM API/推論而非 ES 取件；多程序協作或 rerun 任務預設關閉 prefetch 可降低 stale pending snapshot、重複派工與共享 Prompt cache 壓力。若 ES pending query 本身成為瓶頸，可由 YAML/ES config 明確設小 buffer（例如 5、20、50）試用。

## 2026-07-23 ES pipeline_hash rerun warning and docs

- 任務目的：降低 ES mode `rerun.pipeline_hash` 被誤用造成既有 output 反覆進 pending / rerun 且操作人員不易判斷原因的風險。
- 主要修改內容：ES rerun startup log 在偵測到有效 `pipeline_hash` 時，會額外提示來源（主 YAML、es_config_file，或 YAML 覆寫 config）、生效值、會寫回 ES meta 並參與 pending/fresh hash 比對，以及 hash 與既有 output meta 不一致會導致重跑的風險；新增 `docs/usage/es_pipeline_hash_rerun.md` 說明安全使用方式與排查方向。
- 驗證結果：依規範先執行 requirements 安裝，但 GitHub `peft` dependency clone 仍受 proxy 403 限制；替代與目標驗證 `python -m compileall czjLLM/es_mode/config/rerun_logging.py` 通過，`python -m pytest tests/es_mode/test_steps_es_rerun_logging.py -q` 通過（僅有既有 pytest unknown config option warning）。
- 重要結論：`pipeline_hash` 仍維持 operator-provided 版本標記，不改變 rerun 判斷語意；本次只加強啟動時可觀測性與文件化，避免靜默反覆重跑。

## 2026-07-24 Excel single-stage YAML converted to one-stage multistage format

- 任務目的：將 `czjLLM/yaml/excel_json_singlestage_in_multistage.yaml` 從舊版頂層單階段 `task` 寫法轉為只有一個 `extract` stage 的多階段格式。
- 主要修改內容：保留原 Excel I/O、模型、merge 與 audit merge log 設定；新增單一 `stages` 區塊、`sql_writeback_rules` 與 `sql_flatten_writeback_rules`，讓 `File_result` 由 `extract` stage 寫回，並沿用原 allowed output fields。
- 驗證結果：依規範先執行 `python -m pip install --upgrade pip && python -m pip install -r requirements.txt`，仍因 GitHub `peft` dependency proxy 403 失敗；替代驗證包含 `python -m compileall czjLLM/yaml` 通過。嘗試以 PyYAML 解析 YAML 時，因目前環境缺少 `yaml` / PyYAML 且 requirements 安裝失敗而無法執行。
- 重要結論：此變更只調整 YAML 設定格式，不改 Python 程式、API contract 或核心 pipeline 行為。

## 2026-07-24 SQLite single-stage YAML converted to one-stage multistage format

- 任務目的：依使用者要求，將 SQLite JSON single-stage 相容性 YAML 改寫為「只有一個 extract stage」的多階段格式。
- 主要修改內容：`czjLLM/yaml/sqlite_json_singlestage.yaml` 與 `czjLLM/yaml/sqlite_json_singlestage_in_multistage.yaml` 移除舊版頂層 `task` / `allowed_output_fields` 寫法，改用單一 `stages[].name=extract`、`@taskSetting:Organization Profile Analyzer to json format`、`sql_writeback_rules` 與 `sql_flatten_writeback_rules` 保留原 File_result 寫回與 flatten 欄位契約。
- 驗證結果：依規範先執行 `python -m pip install --upgrade pip && python -m pip install -r requirements.txt`，仍因 GitHub `peft` dependency proxy 403 失敗；嘗試以 PyYAML 解析 YAML 時因目前環境缺少 `yaml` 模組失敗；替代驗證以 Python 靜態檢查確認兩個 YAML 皆只有一個 extract stage、已移除 legacy 頂層 task、保留 taskSetting reference、stage writeback 與 flatten rule。
- 重要結論：此變更只調整設定檔格式，不新增 mock / stub，也不改 pipeline 程式邏輯。
