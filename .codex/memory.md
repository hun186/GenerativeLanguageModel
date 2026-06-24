# Project Memory

## Current Summary

- 

## Recent Changes

### 

-

## 2026-06-23 AGENTS.md 專案內容更新

- 任務目的：將從其他專案複製而來的 AGENTS.md 後半段改為符合本專案的工作指南。
- 主要修改內容：更新專案概覽、開發流程、優先工作路徑、搜尋原則、常用驗證指令與修改規範，移除 FastAPI / Elasticsearch RAG dashboard 等不屬於本專案的描述。
- 驗證結果：以 `python -m compileall czjLLM/pipeline czjLLM/row_processors czjLLM/utilities` 做語法層級檢查。
- 重要結論：本專案主要是 Python 多來源資料處理與 LLM 多階段分析框架，後續 Agent 應優先查看 pipeline、mode、YAML 設定與 LLM infrastructure 相關路徑。

## 2026-06-24 pending_central Windows file lock compatibility

- 任務目的：修正 Windows 執行 `python -m czjLLM.czjLLM_TextProcessing --config yaml/sqlserver_json_multistage_langroute_config.yaml` 時，`czjLLM.prompt_pipeline.pending_central` 在 import 階段直接載入 POSIX-only `fcntl` 導致 `ModuleNotFoundError` 的問題。
- 主要修改內容：將 `pending_central.py` 的鎖檔實作改為依 `os.name` 選擇 Windows `msvcrt.locking` 或 POSIX `fcntl.flock`，避免 Windows import 階段載入 `fcntl`，並保留 JSON console 原子更新流程。
- 驗證結果：`python -m compileall czjLLM/prompt_pipeline/pending_central.py` 通過；`python -m pytest tests/sql_mode/runtime/test_pending_central.py` 通過 3 tests；額外執行 `from czjLLM.prompt_pipeline import pending_central` 與 AST 檢查確認無 top-level `fcntl` import。
- 重要結論：pending running console 現在可在 Windows 與 POSIX 平台共用同一模組 import 路徑；Windows 實際鎖檔行為仍需於 Windows 環境以原始 SQL Server 多階段命令做端到端驗證。

## 2026-06-24 pending running console schedule noop release and local time log

- 任務目的：修正 SQL/Table/ES stream producer 已撈到 pending rows 時，若 `schedule_one_row` 未建立可執行任務或丟出例外，該 pk 可能持續留在 pending running console，造成其他程序一直延後同一列並出現「有撈到應跑任務但未繼續跑」的風險；同時將 `pending_running_console_adjustments.log` 時間格式改為比照 `pending_recheck_skips.log` 的本地時區 ISO 時間。
- 主要修改內容：`record_adjustment` 現在寫入本地時區 `ts` 與 `timezone`；producer 只在 `schedule_one_row` 回傳正數 chunk 時納入 scheduled，回傳 0/None/非數值或例外時會釋放 running console 標記並寫入 `schedule_noop_release` / `schedule_error_release`。
- 驗證結果：`python -m compileall czjLLM/prompt_pipeline/pending_central.py czjLLM/sql_mode/runtime/producer.py` 通過；`python -m pytest tests/sql_mode/runtime/test_pending_central.py tests/sql_mode/runtime/test_producer_pending_recheck.py` 通過可執行測試（部分測試因缺少 optional dependency 仍被既有 `pytest.importorskip` skip）。
- 重要結論：pending running console 不再因切片/排程未產生任務而永久保留 running 狀態；調整記錄 log 可直接以當地時間比對 pending recheck skip log。

## 2026-06-24 pending running console release on writeback and stale pid prune

- 任務目的：追查使用者回報套用前次修正後仍出現 pending rows 被撈到但後續批次被 running console 延後/結束的情況；使用者提供的 `pending_running_console.json` 顯示已完成或舊程序的 pk 仍停留在 `running`。
- 主要修改內容：pending running console 在讀取時會同步清除已不存在 pid 的 running 紀錄；row merger 在 SQL/Table/ES 寫回成功後會呼叫 `mark_not_running(..., state="writeback_completed")` 並記錄 `writeback_completed_release`，讓跨程序 pending 協調以「真正寫回完成」作為釋放點，而不是只依 producer 收尾。
- 驗證結果：`python -m compileall czjLLM/prompt_pipeline/pending_central.py czjLLM/sql_mode/runtime/row_merger_generic.py czjLLM/sql_mode/runtime/producer.py` 通過；`python -m pytest tests/sql_mode/runtime/test_pending_central.py tests/sql_mode/runtime/test_producer_pending_recheck.py` 通過可執行測試（5 passed，1 skipped）。
- 重要結論：前次只處理 schedule no-op/exception，未處理「成功寫回後釋放 running」與「舊 pid 殘留」；這兩者會讓後續程序看到 deferred running rows，造成可用 pending rows 逐步被誤延後。

## 2026-06-24 Windows pid liveness probe fix

- 任務目的：修正前次新增的 dead pid prune 在 Windows producer-thread 啟動時呼叫 `os.kill(pid, 0)` 觸發 `SystemError: <class 'OSError'> returned a result with an exception set` / WinError 87，導致 producer 還沒排程就中止。
- 主要修改內容：`pending_central._pid_is_alive` 在 Windows 改用 Kernel32 `OpenProcess` + `GetLastError` + `GetExitCodeProcess` 檢查 process 是否仍為 `STILL_ACTIVE`，不再使用 `os.kill(pid, 0)`；非 Windows 路徑保留 `os.kill(pid, 0)` 並增加防禦性例外處理。
- 驗證結果：`python -m compileall czjLLM/prompt_pipeline/pending_central.py` 通過；`python -m pytest tests/sql_mode/runtime/test_pending_central.py tests/sql_mode/runtime/test_producer_pending_recheck.py` 通過可執行測試（7 passed，1 skipped）；依專案要求先執行 requirements 安裝但 GitHub dependency 仍受 proxy 403 限制。
- 重要結論：Windows dead pid pruning 不能使用 `os.kill(pid, 0)`；需透過 Win32 process handle API 或 fail-open，避免 liveness probe 影響主流程排程。

## 2026-06-24 multistage stream pre-registers row merger work

- 任務目的：修正 SQL multistage stream 每次只跑一列、多階段完成後未回存 SQL，且 pending running console 只看到 `mark_running_before_dispatch` 沒有 release 的問題。使用者 log 顯示多階段 LLM 已完成並輸出 `_stage_merges`，但過程中 watchdog 一直看到 `reg_empty=True`，代表 row merger 從未取得可寫回工作。
- 主要修改內容：`ItemsRegistry` 新增 thread-safe `update()`；`schedule_one_row` 在 multistage 同步呼叫 LLM 前就先註冊 row merger item 並更新 meter，避免 LLM 執行期間 registry 為空；多階段合併完成後再以實際 `CombBackFN` 更新 registry，讓 row merger 可用成品路徑寫回 SQL。若多階段失敗，會移除預註冊 item，避免殘留。
- 驗證結果：`python -m compileall czjLLM/sql_mode/runtime/scheduler.py czjLLM/prompt_pipeline/pipeline_controller.py` 通過；`python -m pytest tests/sql_mode/runtime/test_pending_central.py tests/sql_mode/runtime/test_producer_pending_recheck.py` 通過可執行測試（7 passed，1 skipped）；requirements 安裝仍受 GitHub dependency proxy 403 限制。
- 重要結論：SQL/Table/ES multistage stream 的 LLM 是在 producer/scheduler 內同步執行，必須在執行前先讓 registry 非空，否則 row merger/orchestrator 無法觀察該列，完成後也不會寫回 SQL。

## 2026-06-24 defer row merger until multistage ready

- 任務目的：修正 multistage 預註冊後 row merger 在 stage 尚未完成時就觀察/嘗試處理 item，導致 console 出現多個 `prepare_env` / multiprocessing spawn，最後 Windows child process `DuplicateHandle` 發生 `PermissionError: [WinError 5] 存取被拒`。
- 主要修改內容：`schedule_one_row` 對 SQL/Table/ES multistage 預註冊 item 後標記 `status="scheduling_multistage"`；多階段合併完成並更新 `CombBackFN` 後改為 `status="ready_for_writeback"`。`row_merger_watchdog_generic` 看到 `scheduling_multistage` 會先跳過，保留 registry 非空給 orchestrator 觀察，但不提前合併/寫回。
- 驗證結果：`python -m compileall czjLLM/sql_mode/runtime/scheduler.py czjLLM/sql_mode/runtime/row_merger_generic.py` 通過；`python -m pytest tests/sql_mode/runtime/test_pending_central.py tests/sql_mode/runtime/test_producer_pending_recheck.py` 通過可執行測試（7 passed，1 skipped）；requirements 安裝仍受 GitHub dependency proxy 403 限制。
- 重要結論：multistage 預註冊只應用於防止 `reg_empty=True`，不應讓 row merger 在 stage runtime 尚未完成時讀取 `TODO/Success` 或嘗試合併；需以 registry status 分隔「已註冊」與「可寫回」。

## 2026-06-24 skip final combine for stage SQL writeback

- 任務目的：修正 SQL multistage 在 stage 都完成、manifest 已輸出後，卡在 `is finished calling API, start to combine returned result.`，接著 Windows multiprocessing child `DuplicateHandle` 發生 `PermissionError: [WinError 5]`，導致未進入 row merger SQL 寫回。
- 主要修改內容：`process_prompt_and_merge_multistage` 偵測到 `sql_writeback_rules` 使用 `source=stage` 時，預設跳過最後的 prompt item `combine_api_finished_item`，改在 `_stage_merges/<main_name>/` 產生輕量 marker 檔並直接回傳；row merger 後續仍透過 marker 路徑尋找 manifest，依 stage writeback rules 讀取 route/extract/audit_json stage merged output 寫回 SQL。
- 驗證結果：`python -m compileall czjLLM/prompt_pipeline/pipeline_controller.py` 通過；`python -m pytest tests/sql_mode/runtime/test_pending_central.py tests/sql_mode/runtime/test_producer_pending_recheck.py` 通過可執行測試（7 passed，1 skipped）；requirements 安裝仍受 GitHub dependency proxy 403 限制。
- 重要結論：當 SQL 寫回來源全由 stage merged output 決定時，不需要再對 prompt item 做最終 combine；跳過該步可避免 Windows multiprocessing/spawn 收尾問題，並讓 scheduler 取得可供 row merger 定位 manifest 的 `CombBackFN`。

## 2026-06-24 final combine skip changed to opt-in

- 任務目的：回應使用者質疑「原本未改 final combine 也可正常跑完，原因會是這裡嗎？」；重新檢視後確認不應把 final combine 預設視為根因，也不應預設改變既有 SQL multistage 行為。
- 主要修改內容：`multistage_stage_writeback_skip_final_combine` 改為 opt-in；即使偵測到 `sql_writeback_rules source=stage`，預設仍保留 legacy final prompt combine。只有使用者明確設定 `multistage_stage_writeback_skip_final_combine=True` 時才跳過 final combine 並使用 stage manifest marker。
- 驗證結果：`python -m compileall czjLLM/prompt_pipeline/pipeline_controller.py` 通過；`python -m pytest tests/sql_mode/runtime/test_pending_central.py tests/sql_mode/runtime/test_producer_pending_recheck.py` 通過可執行測試（7 passed，1 skipped）；requirements 安裝仍受 GitHub dependency proxy 403 限制。
- 重要結論：final combine 可能只是錯誤最後可見位置，不一定是根因；在未完全確認前，避免預設改變既有可正常執行的 combine 流程。
