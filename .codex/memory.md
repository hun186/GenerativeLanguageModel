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
