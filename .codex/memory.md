# Project Memory

## Current Summary

- 本專案是 Python 多來源資料處理與 LLM 多階段分析框架，核心包含資料讀取、prompt/task 設定、多階段 pipeline、LLM 呼叫、結果合併、JSON flatten 與匯出。
- SQL / Table / ES stream 多階段會在 scheduler 階段重用 `process_prompt_and_merge()` 產生 stage merge / manifest，再由 row_merger 寫回。
- 舊單階段 legacy consumer 仍使用 TODO/RUNNING/Success 佇列與 `run_round()` multiprocessing；新版明確 stage flow 會走 stage-managed / scheduler path。
- LLM call audit 會在每次 `czjLLM_TextProcessing` 啟動時建立 CSV/XLSX，token usage 來源為 LLM API response usage，context 使用率優先使用 Ollama `/api/ps` active context。
- requirements 安裝在目前環境仍受 GitHub `peft` dependency proxy 403 限制，需用 compileall、靜態檢查與可收集的目標 pytest 作替代驗證。

## Recent Changes

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

## 2026-08-05 dataset picker None guard after converter label-file failure

- 任務目的：處理使用者 Windows 執行 `python TCFMain.py -ts y -p 8059` 時，DataConverter 先因缺少 `../TACA/DB/ZMRAND/Imported\\TopicTree.csv` 失敗，父流程接著以 `None` datasetDir 呼叫 `CheckDatasetFiles()` 並拋出遮蔽根因的 `TypeError`。
- 主要修改內容：`utils/DataConverter_utils.py` 的 `CheckDatasetFiles()` 現在可接受 `BertDatasetSubDir is None`，回傳三個資料集檔案皆為 False 的明確檢查結果，避免 `os.path.join(None, ...)` 造成二次崩潰；同檔舊註解程式碼字串中的 regex 反斜線也已轉義，避免 `-Werror` 語法檢查被既有 SyntaxWarning 擋住。
- 驗證結果：依規範先執行 `python -m pip install --upgrade pip && python -m pip install -r requirements.txt`，仍因 GitHub `peft` clone proxy 403 失敗；替代驗證 `python -Werror -m py_compile utils/DataConverter_utils.py`、`python -m compileall -q utils/DataConverter_utils.py` 與 AST 擷取 `CheckDatasetFiles(None)` 行為檢查通過。
- 重要結論：此修正不解決缺少 TopicTree 類別樹檔案的原始設定/資料問題，但可讓父流程保留 DataConverter 的 FileNotFoundError 根因，不再追加誤導性的 NoneType path join 錯誤。

## 2026-08-05 TACA class-tree boundary proposal

- 任務目的：回應使用者正在進行模組邊界定義，釐清 TACA 拓撲匯製/可視化專案與階層式文本分類專案之間的類別邊 CSV 責任邊界。
- 主要修改內容：新增 `docs/architecture/taca_class_tree_boundary.md`，建議將執行期 `TopicTree*.csv` 視為文本分類專案 runtime config，由 TACA 保留編輯/可視化角色；同步更新 architecture、decisions 與 backlog，記錄 project-local `config/class_trees/default/`、legacy `../TACA/...` fallback 與後續 loader migration 任務。
- 驗證結果：依規範先執行 requirements 安裝但仍受 GitHub `peft` clone proxy 403 限制；替代驗證包含 `python -Werror -m py_compile utils/DataConverter_utils.py`、`python -m compileall -q utils/DataConverter_utils.py`，以及文件內容 smoke check 確認邊界文件包含 migration guidance。
- 重要結論：短期不要直接刪掉 TACA sibling fallback；建議先把 runtime 依賴改為「明確設定 > 專案內 config > legacy TACA fallback」，再逐步移除隱含 sibling checkout 依賴。

## 2026-08-05 class-tree resolver implementation

- 任務目的：回應使用者指出上一版只有文件而沒有更新讀取階層類別 CSV 的 code。
- 主要修改內容：新增 `utils/class_tree_paths.py`，實作 class-tree CSV 解析順序：明確 `class_tree_root` > `CLASS_TREE_ROOT` > `config/class_trees/default/` > legacy `../TACA/DB/ZMRAND/Imported/`；缺檔時 `FileNotFoundError` 會列出所有 searched paths。`RawAndPredictionMerger.GetInfoScoreTable()` 由硬編碼檔名改為先解析成實際路徑再呼叫既有 `LoadTree()`。新增 `tests/utils/test_class_tree_paths.py` 覆蓋 explicit root、缺檔訊息與檔案順序。
- 驗證結果：依規範先執行 requirements 安裝但仍因 GitHub `peft` clone proxy 403 失敗；替代驗證 `python -m pytest tests/utils/test_class_tree_paths.py -q` 通過（3 passed，保留既有 pytest `env_files` warning），`python -m compileall -q utils/class_tree_paths.py utils/DataConverter_utils.py` 通過。
- 重要結論：目前 repo 只包含 `utils/DataConverter_utils.py` 中的 class-tree 呼叫點；使用者 stack trace 的 `ClassesTree/ClassesTree_utils.py::SetTreeFiles()` 不在此 checkout 中，仍需在實際 text-category-profiler 專案把同一 resolver 接到 `SetTreeFiles()` 才能完整覆蓋 `DatasetConverter/DataConverter.py::loadLabels()` 的失敗路徑。

## 2026-08-05 class-tree local copy guidance

- 任務目的：回應使用者確認是否可先手動把階層關係檔複製到 `config/class_trees/default/`。
- 主要修改內容：新增 `config/class_trees/default/README.md`，列出遷移時應放置的 `TopicTree.csv`、`TopicTree_AK4.csv`、restricted-label 模式用 `TopicTree_PAK.txt`，並記錄 resolver 搜尋順序。
- 驗證結果：文件新增後以 `python - <<'PY' ... PY` 檢查 README 包含必要檔名與搜尋順序；完整 requirements 安裝仍受 GitHub `peft` clone proxy 403 限制。
- 重要結論：短期可手動複製 TACA 下的類別樹檔案到 `config/class_trees/default/`；已接上 `utils.class_tree_paths` 的 code path 會優先使用專案內副本。
