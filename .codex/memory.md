# Project Memory

## Current Summary

- 本專案是 Python 多來源資料處理與 LLM 多階段分析框架，核心包含資料讀取、prompt/task 設定、多階段 pipeline、LLM 呼叫、結果合併、JSON flatten 與匯出。
- SQL / Table / ES stream 多階段會在 scheduler 階段重用 `process_prompt_and_merge()` 產生 stage merge / manifest，再由 row_merger 寫回。
- 舊單階段 legacy consumer 仍使用 TODO/RUNNING/Success 佇列與 `run_round()` multiprocessing；新版明確 stage flow 會走 stage-managed / scheduler path。
- requirements 安裝在目前環境仍受 GitHub `peft` dependency proxy 403 限制，需用 compileall 與目標 pytest 作替代驗證。

## Recent Changes

## 2026-07-16 bounded row-level multistage stream parallelism

- 任務目的：讓 SQL / Table / ES multi-stage stream 不再只能同步逐筆 row/doc 執行，改為可在 row/doc 層級依 GPU / n_process 做有界並行，避免無限制送件導致 timeout。
- 主要修改內容：`sql_mode/runtime/producer.py` 新增 stream multistage 判斷與 row/doc thread pool；預設平行度為 `ctx.n_process`，不以派工主程式本機 GPU 數推估；可用 `multistage_row_parallelism` / `sql_multistage_row_parallelism` / `stream_multistage_row_parallelism` 明確覆寫遠端模型服務可承受的 row/doc 並行量。
- 驗證結果：依規範先執行 `python -m pip install --upgrade pip && python -m pip install -r requirements.txt`，但 GitHub dependency `peft` 仍受 proxy 403 限制；替代驗證包含 `python -m compileall czjLLM/sql_mode/runtime/producer.py` 通過，以及 `python -m pytest tests/sql_mode/runtime/test_producer_pending_recheck.py tests/sql_mode/runtime/test_pending_central.py` 共 10 passed、1 skipped。
- 重要結論：新版多階段 stream 仍保留每筆 row/doc 內部 `schedule_one_row()` 與 writeback 流程，但 producer 可同時維持有限數量 row/doc in-flight；pending running console、pending recheck 與 schedule no-op/error release 仍在每筆 row/doc 任務內執行。


## 2026-07-16 ES rerun required-check scope correction

- 任務目的：回應使用者指出前次「用 article_date_iso / Event.time 回補 Event_Timeline.date_iso」可能影響抽取語意；重新釐清 ES 單階段與多階段重跑差異。
- 主要修改內容：移除前次 `multidim_event` output profile 對缺失 `Event_Timeline` 的語意性回補，保留既有只針對已存在 `Event_Timeline[].date` 做格式正規化的行為；將 ES `required_output_checks` 改為只在 `rerun.enable=true` 時參與 fresh/pending 判斷，若需在 rerun 關閉時仍強制檢查，可明確設定 `required_output_checks_apply_without_rerun=true`。
- 驗證結果：依規範先執行 requirements 安裝，但 GitHub dependency `peft` 仍受 proxy 403 限制；替代驗證包含 `python -m compileall czjLLM/es_mode/adapters/elasticsearch_adapter.py czjLLM/es_mode/output_profiles/multidim_event.py czjLLM/prompt_pipeline/round_runner.py` 通過，以及 `python -m pytest tests/es_mode_test_elasticsearch_pending_multicol.py tests/prompt_pipeline/test_round_runner_smoke.py tests/test_es_sink_output_profile.py tests/test_es_sink_multifield_writeback.py tests/sql_mode/runtime/test_pending_central.py` 共 27 tests 通過。
- 重要結論：`required_output_checks` 是「是否視為需要重跑」的條件，不應透過寫回正規化偽造/補足 LLM 未抽出的事件時間線。多階段 YAML 之所以可控，是因其明確覆寫 `rerun.pipeline_hash` / checks；舊單階段 YAML 若未覆寫 `rerun`，會繼承 `es_config_file` 的 rerun 設定，包含 required checks，因此可能比預期更積極重跑。
## 2026-07-16 LLM round executor fallback narrowed

- 任務目的：回應使用者擔心「Windows 預設改 thread pool」方向過大；重新釐清多階段任務沒問題、掛掉的是舊單階段 consumer 的 `run_round` 路徑。
- 主要修改內容：將 `round_runner` 從「Windows 預設 thread pool」改為「預設維持歷史 multiprocessing；只有未強制指定 executor、且 Windows multiprocessing round 實際遇到 PermissionError / WinError 5 / DuplicateHandle 時，才重試該單階段 round 的 thread pool fallback」。`CZJLLM_LLM_ROUND_EXECUTOR=threads` 仍可主動使用 thread pool；`CZJLLM_LLM_ROUND_EXECUTOR=processes` 會停用 fallback 以利診斷。
- 驗證結果：依規範先執行 requirements 安裝，但 GitHub dependency `peft` 仍受 proxy 403 限制；替代驗證包含 `python -m compileall czjLLM/prompt_pipeline/round_runner.py` 通過，以及 `python -m pytest tests/prompt_pipeline/test_round_runner_smoke.py tests/es_mode_test_elasticsearch_pending_multicol.py tests/test_es_sink_output_profile.py tests/test_es_sink_multifield_writeback.py tests/sql_mode/runtime/test_pending_central.py` 共 29 tests 通過。
- 重要結論：多階段 stream 主要在 scheduler 階段同步執行，不走 `llm_stream_consumer -> run_round` 這條 legacy consumer 派工路徑；因此不應預設改變 Windows executor。保留 multiprocessing 預設並只在單階段 round 觸發 WinError 5 時 fallback，可降低行為變更範圍。
## 2026-07-16 LLM round executor rollback for diagnostics

- 任務目的：依使用者要求，先拿掉 LLM round 多 executor / thread fallback 邏輯，讓單階段任務回到原本 multiprocessing 路徑，以便使用者重跑並收集更直接的錯誤資訊。
- 主要修改內容：移除 `round_runner.py` 的 thread pool import、executor mode helper、Windows handle error detector、threaded runner 與 fallback；`run_round` 回復為 `n_proc>1` 時只使用 `multiprocessing.Pool`。同步移除 thread/fallback 相關測試，保留單程序成功與 timeout 測試。
- 驗證結果：依規範先執行 requirements 安裝，但 GitHub dependency `peft` 仍受 proxy 403 限制；替代驗證包含 `python -m compileall czjLLM/prompt_pipeline/round_runner.py` 通過，以及 `python -m pytest tests/prompt_pipeline/test_round_runner_smoke.py tests/es_mode_test_elasticsearch_pending_multicol.py tests/test_es_sink_output_profile.py tests/test_es_sink_multifield_writeback.py tests/sql_mode/runtime/test_pending_central.py` 共 26 tests 通過。
- 重要結論：目前暫不對 LLM round executor 做行為變更；若使用者重跑後提供更完整單階段 crash stack / pool 狀態 / consumer log，再依證據決定是否修正 multiprocessing 使用方式、consumer lifecycle 或 row merger/combiner 路徑。

## Archived History

- `memory.md-20260716-064228.md`：於 20260716-064228 濃縮前保存完整 `.codex/memory.md` 歷史，涵蓋 2026-06-23 至 2026-07-16 多筆任務紀錄。

## 2026-07-16 multistage parallelism remote Ollama correction

- 任務目的：修正前次 row/doc 並行預設使用派工主機可見 GPU 數的假設；使用者指出 Ollama API 可能在遠端模型服務主機，派工主程式本機不一定看得到 GPU。
- 主要修改內容：移除 producer 的本機 GPU 偵測；未設定 `multistage_row_parallelism` / `sql_multistage_row_parallelism` / `stream_multistage_row_parallelism` 時使用既有單階段 LLM round 的 endpoint-pool-derived `ctx.n_process`；若 `ctx.n_process` 不可用則依 `model_spec.base_url` pool 推導。文件補充遠端 Ollama/OpenAI-compatible API 可由使用者明確設定模型服務可承受的 row/doc 並行量。
- 驗證結果：執行 requirements 安裝仍受 GitHub `peft` dependency proxy 403 限制；替代驗證包含 `python -m compileall czjLLM/sql_mode/runtime/producer.py` 通過，以及 `python -m pytest tests/sql_mode/runtime/test_producer_multistage_parallelism.py tests/sql_mode/runtime/test_producer_pending_recheck.py tests/sql_mode/runtime/test_pending_central.py` 共 13 passed、1 skipped。
- 重要結論：派工端不應用本機 `nvidia-smi` 代表模型服務 GPU 容量；遠端服務容量需透過 endpoint 數、`ctx.n_process` 或明確 row parallelism 參數表達。

## 2026-07-16 endpoint-pool-derived multistage row parallelism

- 任務目的：回應使用者指出程式啟動時已掃 `infrastructure/end_point_config.json` / model endpoint pool，既有單筆內派工數也應直接復用此機制，而不是另建 GPU 推估。
- 主要修改內容：`_multistage_row_parallelism()` 未明確設定時改為復用 `ctx.n_process`，此值在初始化時已由可用 `base_url` endpoint pool 推導；若測試或特殊流程沒有 `ctx.n_process`，則由 `ctx.model_spec["base_url"]` pool 大小推導保底值。
- 驗證結果：執行 requirements 安裝仍受 GitHub `peft` dependency proxy 403 限制；替代驗證包含 `python -m compileall czjLLM/sql_mode/runtime/producer.py` 通過，以及 `python -m pytest tests/sql_mode/runtime/test_producer_multistage_parallelism.py tests/sql_mode/runtime/test_producer_pending_recheck.py tests/sql_mode/runtime/test_pending_central.py` 共 13 passed、1 skipped。
- 重要結論：row/doc 層級 multistage 並行量現在直接復用既有 endpoint pool / `ctx.n_process` 派工容量；每次 LLM 呼叫仍由 `select_idle_ollama_url()` 在 base_url pool 中做租約式負載平衡。

## 2026-07-16 ES single-stage self-envelope writeback fix

- 任務目的：修正 ES 單階段 `multidim_event_json` 寫回時，LLM/合併產物若已包成 `{output_col: [...]}`，再經 row_merger 以同名欄位傳入 ESSink 後形成 `multidim_event_json.multidim_event_json` 且內層 JSON 字串未解析的問題。
- 主要修改內容：`ESSink` 新增單欄位 self-envelope unwrap 與內層 JSON 字串解析；在單欄位、multi-field rule fallback 與直接 payload 寫回路徑中，於 output profile 正規化前移除傳輸包裝，讓單階段與多階段寫回都得到相同的事件 payload shape。
- 驗證結果：依規範先執行 `python -m pip install --upgrade pip && python -m pip install -r requirements.txt`，但 GitHub dependency `peft` 仍受 proxy 403 限制；替代驗證包含 `python -m compileall czjLLM/es_mode/runtime/sinks/es_sink.py` 通過，以及 `python -m pytest tests/es_mode_test_elasticsearch_pending_multicol.py tests/test_es_sink_output_profile.py tests/test_es_sink_multifield_writeback.py` 共 15 tests 通過。
- 重要結論：修正點放在 ES sink 寫回前的 payload normalization boundary，不改變 LLM 抽取、slice merge 或多階段 scheduler；若 payload 不是單鍵同名 envelope，會維持原內容不被任意 unwrap。
