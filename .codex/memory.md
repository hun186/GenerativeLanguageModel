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

## 2026-06-25 pending running console retention and README

- 任務目的：確認並落實 pending running console 的短期中控定位，避免 `pending_running_console.json` 因大量 completed / released 紀錄長期累積而膨脹，並補充 README 說明檔。
- 主要修改內容：`pending_central.py` 新增 `pending_running_console_finished_retention_seconds`，預設只保留 `last_finished` 1 小時；`pending_running_console_adjustments.log` 保持 30 MB 上限、超過時保留較新的後半段；補充 JSON 中控檔損毀後會以空結構重建的測試與文件說明。
- 驗證結果：`python -m compileall czjLLM/prompt_pipeline/pending_central.py` 通過；`python -m pytest tests/sql_mode/runtime/test_pending_central.py` 通過 10 tests；`python -m pytest -rs tests/sql_mode/runtime/test_producer_pending_recheck.py` 因目前環境缺少 `yaml` 套件而全部 skip（requirements 安裝仍受 GitHub dependency proxy 403 限制）。
- 重要結論：`pending_running_console.json` 是可重建的跨程序短期協調檔，不是長期歷史資料庫；真正完成判斷仍依 pending recheck 與輸出目標狀態。

## 2026-07-14 large file split candidate audit

- 任務目的：盤點專案中較肥大的 Python 程式檔，找出後續可拆分的重構候選。
- 主要修改內容：新增 `docs/maintenance/large_file_split_candidates.md`，列出前 10 個拆分候選、粗略行數、拆分理由與建議拆分方向。
- 驗證結果：以 Python 腳本掃描 `.py` 檔行數並用 AST 檢視主要大型模組的 top-level function/class 分布；本次未改 runtime code。
- 重要結論：最優先拆分目標是 `czjLLM/prompt_pipeline/pipeline_controller.py` 與 `czjLLM/utilities/combine_utils.py`；大型 task config 與疑似備份/legacy 檔案應低優先或先確認使用狀態。

## 2026-07-15 prompt pipeline extraction refactor

- 任務目的：依 `docs/maintenance/large_file_split_candidates.md` 開始對肥大程式檔進行拆檔重構，優先處理最大檔 `czjLLM/prompt_pipeline/pipeline_controller.py`。
- 主要修改內容：將 ItemsRegistry/load meter/lock/file cleanup/item lookup helper 抽到 `czjLLM/prompt_pipeline/load_meter.py`；將 TODO/RUNNING/Success 檔案佇列 helper 抽到 `czjLLM/prompt_pipeline/prompt_queue.py`；將 stall watchdog 與 ES heartbeat watchdog 抽到 `czjLLM/prompt_pipeline/watchdogs.py`；`pipeline_controller.py` 改為相容 re-export/import，保留既有 import 路徑。
- 驗證結果：`python -m compileall czjLLM/prompt_pipeline` 通過；新增 `tests/prompt_pipeline/test_extracted_helpers.py` 並通過 3 tests；`python -m pytest tests/sql_mode/runtime/test_pending_central.py` 通過 10 tests；依專案規範先執行 requirements 安裝，但受 GitHub/pip proxy 403 與缺少 runtime dependency 限制，`tests/prompt_pipeline/test_process_prompt_and_merge_di.py` 仍因缺少 `tqdm` 無法收集。
- 重要結論：本次為 extraction-only 拆檔，未變更 public API、prompt dispatch 語意或 meter JSON shape；`pipeline_controller.py` 行數由約 2,971 降至約 2,447。

## 2026-07-15 prompt pipeline runtime support grouping

- 任務目的：回應「拆分後同一子目錄檔案越來越多」的維護性問題，將前次抽出的 prompt pipeline runtime helper 再依功能集中到子目錄。
- 主要修改內容：新增 `czjLLM/prompt_pipeline/runtime_support/` package，並將 `load_meter.py`、`prompt_queue.py`、`watchdogs.py` 移入該 package；`pipeline_controller.py` 改由 `runtime_support` 匯入並繼續 re-export helper 名稱。
- 驗證結果：`python -m compileall czjLLM/prompt_pipeline` 通過；`python -m pytest tests/prompt_pipeline/test_extracted_helpers.py` 通過 3 tests；`python -m pytest tests/sql_mode/runtime/test_pending_central.py` 通過 10 tests；requirements 安裝仍受 proxy 403 限制。
- 重要結論：prompt pipeline 根目錄不再新增三個 runtime helper 檔，相關 helper 集中於 `runtime_support/`，定位方式更清楚。

## 2026-07-15 ES writeback business-key update fix

- 任務目的：修正 prompt pipeline runtime helper 移入 `runtime_support/` 後使用者回測發現 ES 模式顯示 `bulk 成功筆數`，但查詢原 ES 文件時未看到欄位寫回；Excel 與 SQLite 模式正常。
- 主要修改內容：在 `ESSink` flush ES bulk update 前，若 ES 設定的 `id_col` 不是 `_id`，先用 `id_col`/keyword 欄位解析實際 Elasticsearch `_id`，再送出 bulk update，避免把 business key 當成 `_id` 造成 ES 成功 upsert 到另一份新文件而原文件未更新；並在 upsert fallback 時把 business key 寫入 doc。
- 驗證結果：依專案規範先執行 `python -m pip install --upgrade pip && python -m pip install -r requirements.txt`，但 GitHub dependency `peft` 仍受 proxy 403 限制；替代驗證包含 `python -m compileall czjLLM/es_mode/runtime/sinks/es_sink.py czjLLM/prompt_pipeline/runtime_support czjLLM/prompt_pipeline/pipeline_controller.py` 通過，以及 `python -m pytest tests/test_es_sink_multifield_writeback.py tests/prompt_pipeline/test_extracted_helpers.py tests/sql_mode/runtime/test_pending_central.py` 共 15 tests 通過。
- 重要結論：ES `helpers.bulk(update)` 的成功筆數只代表 update/upsert request 被 ES 接受；若 `_id` 用錯，仍可能寫到新文件而不是使用者查詢的來源文件。ES 模式使用非 `_id` business key 時，sink 必須先解析真實 `_id`。

## 2026-07-15 ES bulk parsing errors surfaced and payload normalization

- 任務目的：回應 ES 寫回後出現 `document_parsing_exception`，錯誤指出 `multidim_event_json.Involved_Parties` mapping 期待 object/nested，但收到具體非物件值；確認這是實際 ES 寫入錯誤，不應被當成成功完成。
- 主要修改內容：`multidim_event` output profile 會在寫回前清理 ES nested/object 欄位，將 `Person`、`Involved_Parties`、`Impact`、`Event_Timeline`、`evidence_snippets` 中的 `null`/scalar placeholder 移除或轉為空陣列，並將 `Event`、`importance`、`date_range` 的非 object 值轉為空物件；`ESSink._flush` 遇到 bulk errors 時改為 raise `RuntimeError` 且保留 buffer，避免 row merger 在 ES 拒寫時仍標記逐列寫回完成。
- 驗證結果：依專案規範先執行 `python -m pip install --upgrade pip && python -m pip install -r requirements.txt`，但 GitHub dependency `peft` 仍受 proxy 403 限制；替代驗證包含 `python -m compileall czjLLM/es_mode/output_profiles/multidim_event.py czjLLM/es_mode/runtime/sinks/es_sink.py` 通過，以及 `python -m pytest tests/test_es_sink_output_profile.py tests/test_es_sink_multifield_writeback.py tests/prompt_pipeline/test_extracted_helpers.py tests/sql_mode/runtime/test_pending_central.py` 共 23 tests 通過。
- 重要結論：先前 bulk error 是有問題的真實拒寫，不是可忽略 warning；修正後若 ES mapping 仍拒寫，流程會保留待寫 buffer 並把錯誤往上拋，避免假成功。

## 2026-07-16 legacy ES single-stage YAML writeback compatibility

- 任務目的：修正舊版 ES 單階段 YAML（無 `stage_cfg.stages` / `es_writeback_rules`，僅有 `task`、`input_col`、`output_col`）在新版多階段支援後，LLM 計算完成但 consumer/row merger 無法正常走舊式寫回流程的問題。
- 主要修改內容：新增 stage-managed 判斷 helper，只有 `stage_cfg` 明確啟用或宣告 `stages` / `steps` / `routes` / `router` 時才停用一般 stream consumer；ES 初始化產生的相容 `stage_cfg: {enabled: false, name: single_stage}` 不再被誤判為多階段管理模式。
- 驗證結果：依規範先執行 requirements 安裝，但 GitHub dependency `peft` 仍受 proxy 403 限制；替代驗證包含 `python -m compileall czjLLM/prompt_pipeline/pipeline_controller.py czjLLM/prompt_pipeline/runtime_support/stage_mode.py` 通過，以及 `python -m pytest tests/prompt_pipeline/test_consumer_stage_managed_mode.py tests/prompt_pipeline/test_extracted_helpers.py tests/sql_mode/runtime/test_pending_central.py` 共 15 tests 通過。
- 重要結論：舊版 ES 單階段 YAML 應保留 legacy consumer + combined output 寫回路徑；新版即使只有一個明確 stage，只要 YAML 有宣告 stage flow 或 stage writeback rules，仍會走 stage-managed path。SQL/SQLite/Excel 若未宣告 stage flow，同樣不應受空 `stage_cfg` metadata 影響。

## 2026-07-16 single-stage SQL SQLite Table TXT stage-flow audit

- 任務目的：回覆並驗證舊版 SQL、SQLite、Excel/CSV table、TXT 單階段任務是否會像 ES 舊 YAML 一樣被新版多階段判斷誤導。
- 主要修改內容：將「明確 stage flow」判斷集中到 `prompt_pipeline/runtime_support/stage_mode.py`，同時供 stream scheduler 與 prompt final merge 使用；判斷只接受 `ctx.stages` 或 `ctx.task_config.stages`，不會把一般 `ctx.task` 單階段任務升級成 stage-managed。新增測試覆蓋 SQL/SQLite/table 舊單階段與 TXT 舊單階段/新版 task_config.stages。
- 驗證結果：依規範再次執行 requirements 安裝，但 GitHub dependency `peft` 仍受 proxy 403 限制；替代驗證包含 `python -m compileall czjLLM/prompt_pipeline/pipeline_controller.py czjLLM/prompt_pipeline/runtime_support/stage_mode.py czjLLM/sql_mode/runtime/scheduler.py` 通過，以及 `python -m pytest tests/prompt_pipeline/test_consumer_stage_managed_mode.py tests/prompt_pipeline/test_extracted_helpers.py tests/sql_mode/runtime/test_pending_central.py` 共 17 tests 通過。
- 重要結論：SQL/SQLite/table 舊單階段沒有 `ctx.stages` / `task_config.stages` 時會走 legacy consumer + combined writeback；TXT 舊單階段也不會走 multistage final merge。若新版 YAML 明確宣告單一 stage，則仍會走 stage-managed path，這是預期行為。

## 2026-07-16 legacy single-stage misdetection root-cause clarification

- 任務目的：釐清為何既有 scheduler 已有 `ctx.stages` list 判斷，舊單階段仍會被誤判為 stage-managed。
- 主要修改內容：在 consumer stage-managed 判斷旁補充註解，說明根因不是 scheduler 的 `ctx.stages` helper，而是 `llm_stream_consumer` 曾把任意 `ctx.stage_cfg` dict（包含 `{}` 或 `enabled=false/name=single_stage` 相容 metadata）當成 stage-managed 訊號；新增測試確認 `{}` 與 compatibility-only stage_cfg 都不會宣告 flow。
- 驗證結果：requirements 安裝仍受 GitHub dependency `peft` proxy 403 限制；替代驗證包含 `python -m compileall czjLLM/prompt_pipeline/pipeline_controller.py czjLLM/prompt_pipeline/runtime_support/stage_mode.py czjLLM/sql_mode/runtime/scheduler.py` 通過，以及 `python -m pytest tests/prompt_pipeline/test_consumer_stage_managed_mode.py tests/prompt_pipeline/test_extracted_helpers.py tests/sql_mode/runtime/test_pending_central.py` 共 17 tests 通過。
- 重要結論：舊 helper 對 `ctx.stages` 的判斷本身沒有把 plain single task 誤判；漏判發生在另一條 consumer disabled 條件 `has_stage_cfg = isinstance(ctx.stage_cfg, dict)`，空 dict 也會成立，導致舊單階段 consumer 被停用。

## 2026-07-16 single-stage vs multistage YAML guide

- 任務目的：依使用者要求新增說明文件，整理舊版單階段 YAML 與新版多階段 YAML 的寫法注意事項與流程原理。
- 主要修改內容：新增 `docs/usage/single_stage_vs_multistage_yaml_guide.md`，涵蓋 ES、SQL/SQLite、Excel/CSV table、TXT 的舊單階段範例、新版多階段範例、stage-managed 判斷規則、legacy consumer 流程、多階段 manifest/writeback 流程與常見問題。
- 驗證結果：以 Python 腳本檢查文件存在、標題與必要章節（舊版單階段 YAML 寫法、新版多階段 YAML 寫法、多階段流程原理、寫法注意事項）皆存在；本次僅新增文件，未執行 pytest。
- 重要結論：文件明確說明舊單階段應省略 `stage_cfg` / `stages` / `task_config.stages`，不要用空設定表示單階段；新版即使只有一個明確 stage，也會走 stage-managed path。
