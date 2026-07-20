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
- 驗證結果：依規範先執行 requirements 安裝，但 GitHub dependency `peft` 仍受 proxy 403 限制；替代驗證包含 `python -m compileall czjLLM/prompt_pipeline/round_runner.py` 通過，以及 `python -m pytest tests/prompt_pipeline/test_round_runner_smoke.py tests/es_mode_test_elasticsearch_pending_multicol.py tests/test_es_sink_output_profile.py tests/test_es_sink_multifield_writeback.py tests/sql_mode/runtime/test_pending_central.py` 共 30 tests 通過。
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

## 2026-07-16 ES rerun configuration diagnostics

- 任務目的：降低 ES 單階段 / 多階段 YAML 與 `es_config_file` 同時存在 `rerun` 設定時，因隱性繼承或覆寫造成使用者誤判 pending / 重跑行為的風險。
- 主要修改內容：新增 `czjLLM/es_mode/config/rerun_logging.py`，集中處理 ES rerun 淺層合併診斷；`resolve_es_connection()` 在建立 adapter 前輸出醒目的 rerun 來源、覆寫 key、繼承 key、僅主 YAML key 與生效設定摘要，並提示 `enable=true` 會讓 meta / pipeline_hash / force_since / required checks 影響既有 output 是否重新 pending。
- 驗證結果：依規範先執行 `python -m pip install --upgrade pip && python -m pip install -r requirements.txt`，但 GitHub dependency `peft` 仍受 proxy 403 限制；替代驗證包含 `python -m compileall czjLLM/es_mode/entry/steps_es.py czjLLM/es_mode/config/rerun_logging.py` 通過，以及 `python -m pytest tests/es_mode/test_steps_es_rerun_logging.py tests/es_mode_test_elasticsearch_pending_multicol.py` 共 6 passed、2 warnings。
- 重要結論：ES rerun 合併規則仍維持既有行為（主 YAML 同名 key 覆寫 `es_config_file.rerun`，未覆寫 key 會繼承），本次只增加終端機可見診斷，不改變 pending 判斷語意。

## 2026-07-16 SQL Server flatten nested JSON binding fix

- 任務目的：協助使用者測試 SQL Server 模式舊單任務 YAML 時，排查 `子表寫回失敗 ... Invalid parameter type ... param-type=dict` 問題。
- 主要修改內容：`safe_sql_value()` 現在會將 dict 與含巢狀 dict/list 的 list 序列化為 JSON 字串後再交給 SQL / ODBC 綁定，保留純 scalar list 以逗號串接的舊行為；新增單元測試覆蓋 dict、list[dict] 與 scalar list。
- 驗證結果：依規範先執行 `python -m pip install --upgrade pip && python -m pip install -r requirements.txt`，但 GitHub dependency `peft` 仍受 proxy 403 限制；替代驗證包含 `python -m compileall czjLLM/sql_utils/common.py czjLLM/sql_utils/writer.py` 通過，以及 `python -m pytest tests/sql_utils/test_common_safe_sql_value.py` 共 3 passed。嘗試執行 `python -m pytest tests/sql_utils/test_common_safe_sql_value.py tests/sql_mode/runtime/test_row_merger_flatten_targets.py` 時，因目前環境缺少 PyYAML 且 requirements 安裝失敗，`test_row_merger_flatten_targets.py` collection 被 `ModuleNotFoundError: No module named 'yaml'` 阻擋。
- 重要結論：使用者 YAML 若啟用 flatten，MultiDim 任務輸出中的 `Event` / `Person` / `Impact` 等欄位可能是 dict/list；這些欄位不應直接傳給 pyodbc，而應以 JSON 字串保存到子表欄位。若不需要子表展平，可在 YAML 明確設定 `flatten_json_output: false` 並移除/關閉 flatten 規則。

## 2026-07-16 config YAML subdirectory fallback

- 任務目的：讓 `--config sqlserver_json_singlestage_in_multistage.yaml` 這類只輸入檔名的 CLI 呼叫，能在原始輸入路徑找不到時自動搜尋常用 `yaml/` 子目錄。
- 主要修改內容：`resolve_config_path()` 現在先保留原有相對路徑優先順序（cwd、app root、caller dir、project root），並在每個搜尋根目錄後追加 `yaml/<config>` fallback；候選路徑會去重，避免錯誤訊息列出重複嘗試路徑；若使用者已輸入 `yaml/...` 則不再產生 `yaml/yaml/...`。
- 驗證結果：依規範先執行 `python -m pip install --upgrade pip && python -m pip install -r requirements.txt`，但 GitHub dependency `peft` 仍受 proxy 403 限制；替代驗證包含 `python -m compileall utils_manager/utils_sync.py` 通過，以及 `python -m pytest tests/utils_manager/test_utils_sync_config_path.py` 共 3 passed、1 warning。
- 重要結論：設定檔解析仍最先尊重使用者輸入的路徑；只有找不到時才搜尋 `yaml/` fallback，符合既有 CLI 行為並改善 bare filename 的可用性。

## 2026-07-16 single-stage JSON list preservation with merge_slices

- 任務目的：修正單任務 YAML 在 `merge_slices: true` 時，若單一 LLM 成功輸出本身就是含兩筆以上 dict 的 JSON list，合併結果被 `merge_dict_slices_audited()` 壓成單一 dict，導致只保留第一筆組織資料的問題。
- 主要修改內容：`combine_api_finished_item()` 新增 JSON slice 計數；只有實際存在兩個以上成功 JSON slice 時才套用 slice-level dict merge。單一成功 slice 若回傳多筆 dict list，會維持 list 寫回，以便 SQL flatten / writeback 可保存全部項目。新增回歸測試覆蓋 `merge_slices=True` 且單一 JSON list 含「海巡署 / 警政署」兩筆資料時，輸出仍為兩筆 list。
- 驗證結果：依規範先執行 `python -m pip install --upgrade pip && python -m pip install -r requirements.txt`，但 GitHub dependency `peft` 仍受 proxy 403 限制；替代驗證包含 `python -m compileall czjLLM/utilities/combine_utils.py tests/test_combine_json_slice_merge.py` 通過，以及 `python -m pytest tests/test_combine_json_slice_merge.py` 共 4 passed、1 warning。
- 重要結論：`merge_slices` 應只合併多個切片之間的 dict 結果，不應把同一個 LLM 輸出 JSON list 內的多個實體誤視為多個切片並合成單一 dict。


## 2026-07-17 merge_slices documentation clarification

- 任務目的：回應使用者指出 `merge_slices` 是關鍵且容易產生疑義的程式邏輯，需確認並補足說明文件。
- 主要修改內容：在 `docs/usage/single_stage_vs_multistage_yaml_guide.md` 補充 `merge_slices` 的語意：只做跨 prompt slice 合併，不會把單一 LLM 回覆 JSON list 內的多個 dict 實體壓成一筆；並在 SQL Server 單任務 YAML 範例旁加註同一原則。
- 驗證結果：執行 `python -m compileall czjLLM/utilities/combine_utils.py tests/test_combine_json_slice_merge.py` 通過，以及 `python -m pytest tests/test_combine_json_slice_merge.py` 共 4 passed、1 warning。
- 重要結論：文件現在明確區分「跨 slice 合併」與「單一 JSON list 內多實體保留」，避免使用 `merge_slices: true` 時誤解輸出 shape。

## 2026-07-17 Windows legacy single-stage LLM round executor fix

- 任務目的：修正 Windows 執行舊版單階段 ES YAML 時，legacy consumer 在 `run_round()` 使用 multiprocessing spawn 可能於子程序重建 pipe handle 時觸發 `PermissionError: [WinError 5] DuplicateHandle`，導致已完成 LLM 回覆後無法穩定進入合併/寫回流程。
- 主要修改內容：`czjLLM/prompt_pipeline/round_runner.py` 將 legacy 單階段 consumer 的平行 LLM round executor 抽成 processes / threads 兩條路徑；Windows 未明確指定時預設使用 thread pool，避免 spawn / DuplicateHandle；Linux 與其他平台預設保留 multiprocessing。可用 `CZJLLM_LLM_ROUND_EXECUTOR=processes` 強制回到舊 multiprocessing 診斷，也可用 `threads` 主動指定 thread pool。
- 驗證結果：依規範先執行 `python -m pip install --upgrade pip && python -m pip install -r requirements.txt`，但 GitHub dependency `peft` 仍受 proxy 403 限制；替代驗證包含 `python -m compileall czjLLM/prompt_pipeline/round_runner.py tests/prompt_pipeline/test_round_runner_smoke.py` 通過，以及 `python -m pytest tests/prompt_pipeline/test_round_runner_smoke.py tests/es_mode_test_elasticsearch_pending_multicol.py tests/test_es_sink_output_profile.py tests/test_es_sink_multifield_writeback.py tests/sql_mode/runtime/test_pending_central.py` 共 30 tests 通過。
- 重要結論：此修正只影響 legacy single-stage consumer 的每輪 LLM API 呼叫派工；多階段 stream scheduler 與 Linux 預設行為不變。Windows 下 LLM API 呼叫屬 I/O-bound，thread pool 可保留 endpoint 並行且避開 multiprocessing handle 權限問題。

## 2026-07-17 Windows legacy single-stage debug-first rollback

- 任務目的：回應使用者指出舊版單階段任務過去使用 multiprocessing 並未在 Windows 發生 `WinError 5`，因此不應先直接改 Windows executor 預設，而應先釐清近期程式變更造成的 pool / spawn / handle 狀態差異。
- 主要修改內容：撤回 Windows 預設 thread pool 的行為變更，`run_round()` 回到所有平台平行 round 預設使用 multiprocessing；新增 `CZJLLM_LLM_ROUND_DEBUG=1` 診斷開關，會在 multiprocessing pool 建立前後、join 後、timeout 或 exception 時輸出平台、PID、start method、active children、n_proc、jobs、pool processes、worker target 與 prompt job sample，協助比對 Windows crash 前後狀態。
- 驗證結果：依規範先執行 requirements 安裝，但 GitHub dependency `peft` 仍受 proxy 403 限制；替代驗證包含 `python -m compileall czjLLM/prompt_pipeline/round_runner.py tests/prompt_pipeline/test_round_runner_smoke.py` 通過，以及 `python -m pytest tests/prompt_pipeline/test_round_runner_smoke.py tests/es_mode_test_elasticsearch_pending_multicol.py tests/test_es_sink_output_profile.py tests/test_es_sink_multifield_writeback.py tests/sql_mode/runtime/test_pending_central.py` 共 30 tests 通過。
- 重要結論：下一步建議請使用者在 Windows 以 `set CZJLLM_LLM_ROUND_DEBUG=1` 後重跑同一 YAML，保留從 `[round-debug] phase=before_pool` 到 crash 的完整 log，以確認是 pool 建立、apply_async job pickle、child import、或 combine/writeback 期間的子程序 handle 重建問題。

## 2026-07-17 Windows legacy single-stage active-child fallback

- 任務目的：根據使用者提供的 `CZJLLM_LLM_ROUND_DEBUG=1` log 進一步縮小 Windows 單階段 crash 原因；log 顯示 crash 前只有 `phase=before_pool`，未到 `after_pool_created`，且建立新 Pool 前 `active_children=1`、`thread=consumer-thread`、start method 為 `spawn`。
- 主要修改內容：保留 multiprocessing 預設，不改 `CZJLLM_LLM_ROUND_EXECUTOR`；新增 Windows 專用保護：若 legacy single-stage round 準備建立 Pool 前偵測到既有 multiprocessing child，該 round 改為序列執行，避免在 Windows spawn / DuplicateHandle 狀態重疊時建立新 Pool。後續已改為內建安全路徑，不再要求操作人員設定環境變數。
- 驗證結果：依規範先執行 requirements 安裝但 GitHub dependency `peft` 仍受 proxy 403 限制；替代驗證包含 `python -m compileall czjLLM/prompt_pipeline/round_runner.py tests/prompt_pipeline/test_round_runner_smoke.py` 通過，以及 `python -m pytest tests/prompt_pipeline/test_round_runner_smoke.py tests/es_mode_test_elasticsearch_pending_multicol.py tests/test_es_sink_output_profile.py tests/test_es_sink_multifield_writeback.py tests/sql_mode/runtime/test_pending_central.py` 共 32 tests 通過。
- 重要結論：多階段 YAML 正常是因為它走 SQL/ES/Table 共用 multistage scheduler / row-level path，不走 legacy consumer 的 `run_round()` Pool；舊單階段 YAML 會在 consumer thread 中用 `multiprocessing.Pool` 做 round-level dispatch，因此 Windows spawn overlap 只暴露在舊路徑。

## 2026-07-17 Windows spawn-overlap pre-Pool reap tuning

- 任務目的：回應使用者希望直接調優 legacy multiprocessing 路徑，而不是遇到 active child 就立刻降低為序列執行；同時說明為何以前 multiprocessing 正常、近期才出現問題。
- 主要修改內容：Windows legacy single-stage round 在建立新 Pool 前若發現 `active_children > 0`，會先短暫 `join()` 既有 child 嘗試回收已結束或即將結束的子程序；只有 join 後仍有 active child，才對該 round 啟用序列 fallback。pre-Pool join/reap 等待秒數內建為 0.75 秒，不需操作人員設定。
- 驗證結果：依規範先執行 requirements 安裝但 GitHub dependency `peft` 仍受 proxy 403 限制；替代驗證包含 `python -m compileall czjLLM/prompt_pipeline/round_runner.py tests/prompt_pipeline/test_round_runner_smoke.py` 通過，以及 `python -m pytest tests/prompt_pipeline/test_round_runner_smoke.py tests/es_mode_test_elasticsearch_pending_multicol.py tests/test_es_sink_output_profile.py tests/test_es_sink_multifield_writeback.py tests/sql_mode/runtime/test_pending_central.py` 共 33 tests 通過。
- 重要結論：推測近期才出現的關鍵差異不是 multiprocessing 本身，而是舊單階段 stream 現在 consumer / row-merger / producer 以多執行緒協作、第一輪成功與合併寫回可和下一輪 Pool 建立重疊；Windows spawn 對既有 child handle / preparation pipe 狀態較敏感，因此在 active child 尚未完全回收時建立新 Pool 會出現 EOF / DuplicateHandle。

## 2026-07-17 Windows spawn-overlap operator-facing simplification

- 任務目的：回應使用者擔心專案設定越來越多、操作人員難掌握；將 Windows spawn overlap 調優改為系統內建邏輯，而非要求使用者設定環境變數。
- 主要修改內容：移除 `CZJLLM_WINDOWS_SPAWN_OVERLAP_JOIN_TIMEOUT_SEC` 與 `CZJLLM_WINDOWS_SPAWN_OVERLAP_FALLBACK` 操作參數；保留內建 0.75 秒 pre-Pool join/reap，若仍有 active child 則自動序列執行該 round，並在畫面印出提示「automatic safety path; no operator setting is required」。
- 驗證結果：依規範先執行 requirements 安裝但 GitHub dependency `peft` 仍受 proxy 403 限制；替代驗證包含 `python -m compileall czjLLM/prompt_pipeline/round_runner.py tests/prompt_pipeline/test_round_runner_smoke.py` 通過，以及 `python -m pytest tests/prompt_pipeline/test_round_runner_smoke.py tests/es_mode_test_elasticsearch_pending_multicol.py tests/test_es_sink_output_profile.py tests/test_es_sink_multifield_writeback.py tests/sql_mode/runtime/test_pending_central.py` 共 32 tests 通過。
- 重要結論：此類 Windows runtime 保護屬系統自我修復邏輯，不應暴露為一般操作設定；操作人員只需看到終端提示，知道本 round 已自動避開 Windows spawn overlap。

## 2026-07-17 LLM round debug YAML setting documentation

- 任務目的：回應使用者詢問 `CZJLLM_LLM_ROUND_DEBUG=1` 的作用、是否有說明檔，以及能否用 YAML 設定。
- 主要修改內容：`run_round()` 新增 `debug_enabled` 參數；legacy consumer 從 `ctx.llm_round_debug` 傳入，主程式會讀取 YAML 的 `llm_round_debug`。保留 `CZJLLM_LLM_ROUND_DEBUG=1` 作為臨時環境變數診斷方式。文件 `docs/usage/single_stage_vs_multistage_yaml_guide.md` 新增 legacy LLM round debug 說明與 YAML 範例。
- 驗證結果：依規範先執行 requirements 安裝但 GitHub dependency `peft` 仍受 proxy 403 限制；替代驗證包含 `python -m compileall czjLLM/prompt_pipeline/round_runner.py czjLLM/prompt_pipeline/pipeline_controller.py czjLLM/czjLLM_TextProcessing.py czjLLM/job_manager/job_config.py tests/prompt_pipeline/test_round_runner_smoke.py` 通過，以及 `python -m pytest tests/prompt_pipeline/test_round_runner_smoke.py tests/es_mode_test_elasticsearch_pending_multicol.py tests/test_es_sink_output_profile.py tests/test_es_sink_multifield_writeback.py tests/sql_mode/runtime/test_pending_central.py` 共 32 tests 通過。
- 重要結論：`llm_round_debug: true` 只開啟 legacy consumer round-level 診斷輸出，不改 prompt、LLM 輸出或寫回格式；一般任務可省略。

## 2026-07-17 Windows legacy spawn-overlap thread fallback

- 任務目的：使用者提供 Windows 舊單階段 ES YAML 與 Linux 對照 log；Windows 在第一輪完成後看到 `active_children=1` 並進入 pre-Pool reap，後續不像 Linux 能快速維持多個 pending/running 任務，疑似序列安全路徑造成吞吐停滯或看似自行停止。
- 主要修改內容：`czjLLM/prompt_pipeline/round_runner.py` 保留 Windows pre-Pool join/reap；若仍有 active multiprocessing child，不再把該 round 改成完全序列，而是使用 `ThreadPoolExecutor` 執行本 round 的 `PromptAPIPipeline.proc()`，避開 Windows spawn/DuplicateHandle，同時保留 LLM API I/O 併發。非 Windows 與 join/reap 後 child 清空的 Windows round 仍走原 multiprocessing Pool。
- 驗證結果：依規範先執行 `python -m pip install --upgrade pip && python -m pip install -r requirements.txt`，但 GitHub dependency `peft` clone 仍受 proxy 403 限制；替代驗證包含 `python -m compileall czjLLM/prompt_pipeline/round_runner.py tests/prompt_pipeline/test_round_runner_smoke.py` 通過，以及 `python -m pytest tests/prompt_pipeline/test_round_runner_smoke.py` 共 8 passed、1 warning。
- 重要結論：此修正不是把 Windows 全面改成 thread pool；只有在已觀測到 spawn overlap 風險且 short reap 無法清空 active child 時，才對該 round 使用 thread fallback。這符合使用者 log 顯示的實際觸發點，也避免序列 fallback 讓單階段 ES 批次看起來停住。

## 2026-07-17 combine debug YAML switch and debug docs

- 任務目的：使用者指出 `combine_api_finished_item()` 先前為 debug 加入大量 `[combine-step]` / `CombBackFN` 訊息，問題修好後仍洗版；需要改成可由 YAML 開啟，並集中整理 debug 功能文件。
- 主要修改內容：新增 `combine_debug` YAML/ctx 開關與 `CZJLLM_COMBINE_DEBUG` 臨時環境變數覆寫；預設關閉 combine checkpoint，但依使用者回饋保留單行 `CombBackFN` 診斷列，並保留 JSON 解析失敗、修復失敗、清理失敗等重要警告。新增 `docs/usage/debug_features.md` 集中說明 `llm_round_debug`、`combine_debug`、`debug_print_llm_io` / `debug_print_max_chars` 的用途、範例與注意事項，並在 single-stage vs multistage guide 加入口徑。
- 驗證結果：依規範先執行 `python -m pip install --upgrade pip && python -m pip install -r requirements.txt`，但 GitHub dependency `peft` clone 仍受 proxy 403 限制；替代驗證包含 `python -m compileall czjLLM/utilities/combine_utils.py czjLLM/czjLLM_TextProcessing.py czjLLM/job_manager/job_config.py tests/test_combine_json_slice_merge.py` 通過，以及 `python -m pytest tests/test_combine_json_slice_merge.py` 共 6 passed。另執行 `python -m pytest tests/test_combine_json_slice_merge.py tests/prompt_pipeline/test_round_runner_smoke.py` 時，combine 測試已通過，但既有 round_runner Windows spawn-overlap 測試 `test_windows_spawn_overlap_join_clear_allows_pool` 失敗，與本次 combine debug 修改無直接關聯。
- 重要結論：正式批次可省略 `combine_debug` 以避免大量 `[combine-step]` 訊息干擾進度列；單行 `CombBackFN` 會保留。需要定位分片合併、輸出路徑或工作目錄清理問題時，再於 YAML 設定 `combine_debug: true` 或臨時設定 `CZJLLM_COMBINE_DEBUG=1`。

## 2026-07-17 CombBackFN single-line diagnostic retained

- 任務目的：使用者回饋 `CombBackFN` 只有一行可以保留，前次把它也納入 `combine_debug` gating 過度安靜。
- 主要修改內容：調整 `combine_api_finished_item()`，讓大量 `[combine-step]` checkpoint 仍受 `combine_debug` / `CZJLLM_COMBINE_DEBUG` 控制，但 `CombBackFN` 單行輸出固定保留。同步更新 debug 集中說明與 combine 測試預期。
- 驗證結果：依規範重跑 `python -m pip install --upgrade pip && python -m pip install -r requirements.txt`，仍因 GitHub `peft` dependency proxy 403 失敗；替代驗證包含 `python -m compileall czjLLM/utilities/combine_utils.py tests/test_combine_json_slice_merge.py` 通過，以及 `python -m pytest tests/test_combine_json_slice_merge.py` 共 6 passed、1 warning。
- 重要結論：正式批次預設只會保留單行 `CombBackFN` 與必要警告；需要完整 combine trace 時才開 `combine_debug`。

## 2026-07-20 SQLite / Excel legacy single-stage compatibility YAMLs

- 任務目的：為舊版單任務設定檔相容性驗測補齊 SQLite 與 Excel 對照 YAML，並從既有多階段設定中提取核心 `extract` 組織抽取任務，讓 ES / SQL Server / SQLite / Excel 單階段驗測標準一致。
- 主要修改內容：新增 `czjLLM/yaml/sqlite_json_singlestage_in_multistage.yaml`，沿用 SQLite 多階段 `mode=sql`、`File` -> `File_result` 與 `akconfig_local_file_test_multistage.py`，但移除 route / audit_json，只保留 `Organization Profile Analyzer to json format` 舊版單任務核心。新增 `czjLLM/yaml/excel_json_singlestage_in_multistage.yaml`，沿用 Excel 多階段來源/輸出檔案與 target sheet，並使用多階段 org extract 路徑實際的 `Text` 欄位作為單階段輸入。
- 驗證結果：依規範先執行 `python -m pip install --upgrade pip && python -m pip install -r requirements.txt`，但 GitHub dependency `peft` 仍受 proxy 403 限制；替代檢查執行 `python -m compileall czjLLM/yaml` 通過。嘗試用 PyYAML 解析新增 YAML 時，因目前環境缺少 `yaml` / PyYAML 而失敗，需在完整 requirements 可安裝環境重跑 YAML parse / CLI dry run。
- 重要結論：本次只新增相容性測試設定檔，不改 runtime 程式碼、API contract 或資料流；Excel 單階段設定刻意使用 `Text` 而非全域多階段 `input_col: File`，以對齊多階段 extract/org 路徑真正送入 LLM 的欄位。
