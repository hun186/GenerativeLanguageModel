# architecture


---

## 

- 
## 2026-07-15 prompt pipeline helper module split

- `czjLLM/prompt_pipeline/pipeline_controller.py` 仍是 prompt pipeline 的相容入口與主要 orchestration 模組，但 load meter、prompt filesystem queue、watchdog helper 已集中到 `runtime_support/` 子 package。
- `czjLLM/prompt_pipeline/runtime_support/load_meter.py` 負責 `ItemsRegistry`、meter 檔案初始化/讀寫/更新、簡易 lock file、safe unlink 與 item directory lookup。
- `czjLLM/prompt_pipeline/runtime_support/prompt_queue.py` 負責 TODO/RUNNING/Success 檔案佇列操作，例如 claim prompt、path conversion 與 RUNNING 回復 TODO。
- `czjLLM/prompt_pipeline/runtime_support/watchdogs.py` 負責 progress stall watchdog 與 Elasticsearch heartbeat watchdog；透過 `runtime_support.load_meter.meter_read` 讀取 queue 狀態，透過 `round_runner.CONSUMER_STATE` 判斷 dispatch 活動。
- 為降低風險，`pipeline_controller.py` 仍 re-export 這些 helper 名稱，使既有 `from czjLLM.prompt_pipeline.pipeline_controller import ...` 呼叫可繼續運作。

## 2026-07-16 bounded row-level multistage stream dispatch

- SQL / Table / ES stream multistage still executes each row/doc through `schedule_one_row()` and `process_prompt_and_merge()` so the existing stage merge and row_merger writeback contracts remain unchanged.
- The producer can now keep multiple row/doc scheduling jobs in flight via a bounded thread pool when explicit stage flow is enabled. The default bound reuses `ctx.n_process`, the endpoint-pool-derived budget already used by legacy single-stage LLM rounds; when `ctx.n_process` is unavailable it falls back to the available `model_spec.base_url` pool size. The dispatcher intentionally does not infer GPU count from the local host because Ollama/OpenAI-compatible model APIs may run on remote machines.
- Operators may override the bound with `multistage_row_parallelism`, `sql_multistage_row_parallelism`, or `stream_multistage_row_parallelism`; the explicit value should be set conservatively according to the model service capacity to avoid model-side queueing.

## 2026-08-21 independent slice-level dispatch budget

- `czjLLM/prompt_pipeline/dispatch_parallelism.py` 獨立解析 prompt slice worker budget，不與 SQL/Table/ES producer 的 row/doc worker budget 混為同一個設定。
- `call_llm_api()` 在建立一批 TODO slice jobs 後，使用 `multistage_slice_parallelism`（相容 alias: `llm_slice_parallelism`, `slice_parallelism`）限制 worker；未設定時回退既有 `ctx.n_process`。
- 因此 ES/SQL/Table 多階段可在批次尾端只剩長 doc 時繼續將該 doc 的多個 slice 分散到 endpoint pool；後續 stage 若只生成單一 prompt，仍是不可再拆的單 job barrier。
- Parallelism 政策的預設資料來源是 model profile：`initialize_config()` 優先將 `n_process` / 相容 `nProcess` 投影成 `ctx.n_process`，未配置才自動推導；slice 可另用 model-level `slice_parallelism` 覆寫。任務/YAML 參數只作為更高優先序的單次 override。

## 2026-07-20 per-run LLM call audit

- `czjLLM.czjLLM_TextProcessing` 啟動後會建立一次性的 LLM call audit run metadata，掛在 `ctx.llm_call_audit_run_id` 與 `ctx.llm_call_audit_path`。
- `czjLLM/utilities/llm_call_audit.py` 是 append-only CSV audit helper，負責建立 `logs/llm_call_audit/llm_call_audit_<timestamp-pid>.csv`、維護 `latest_llm_call_audit.csv` 指標、解析 usage tokens 與 context limit。
- `PromptAPIPipeline` 在每次實際 `CallLLMAPI()` 成功後記錄 task、prompt file、model、endpoint、input/output/total tokens、context limit、context usage ratio、context exhausted flag、max_tokens 與 cost；呼叫例外時也記錄失敗 row（token 欄位為 0），方便追查中斷前最後一次呼叫。

## 2026-07-20 LLM context metadata resolution

- LLM call audit 的 context limit 不再由 model display name 推估；`llm_call_audit.resolve_context_limit()` 依序使用 response extension、Ollama `/api/show` model metadata、明確 `model_spec` 欄位，最後才回傳 unknown。
- `CallLLMAPI()` 在既有 token usage log 旁新增 context limit log line；token counts 仍取自 chat completion response `usage`，context limit 則來自模型 metadata 查詢或明確設定，兩者來源分開標示。
- Audit CSV 新增 `context_limit_source`，用於區分 `response`、`ollama_api_show`、`model_spec` 或 `unknown`，避免操作人員誤以為 context 是從模型名稱猜出。

## 2026-07-20 LLM audit Excel artifact

- LLM call audit now writes paired artifacts per run: append-only CSV plus a same-stem `.xlsx` workbook under `logs/llm_call_audit/`.
- The workbook is regenerated from the CSV after each audit append and `latest_llm_call_audit.xlsx` points at the newest run, matching the existing CSV pointer behavior.
- The `.xlsx` writer uses Python standard-library ZIP/XML generation to avoid requiring optional Excel dependencies during runtime logging.

## 2026-07-28 combine utility module split

- `czjLLM/utilities/combine_utils.py` 保留完成檔案 orchestration、輸出路徑與 legacy 相容入口，並 re-export 原有 JSON 與 slice merge 公開函式，避免既有 import 路徑中斷。
- `czjLLM/utilities/json_combining.py` 集中 JSON array 分段、repair 與 LLM JSON 回傳正規化；不再為單層 list flatten 載入廣泛的 legacy `utils.utilities` 相依樹。
- `czjLLM/utilities/slice_merge.py` 集中 slice merge 開關、遞迴 dict merge 與 audited merge strategy，供 SQL row merger 與 combine orchestration 共用。
- 原 `combine_utils.py` 內 1,300 多行的手動 `__main__` 範例資料已移除；行為驗證由 `tests/test_combine_json_slice_merge.py` 負責。

## 2026-07-28 Elasticsearch adapter policy boundary

- `es_mode/adapters/elasticsearch_adapter.py` 負責連線、mapping、pending scan 與 adapter 對外介面。
- `es_mode/adapters/pending_policy.py` 以 mixin 集中 output completeness、required checks、freshness/rerun 與 bulk presence policy。
- `es_mode/adapters/value_helpers.py` 提供不依賴 ES client 的文件 dotted-path traversal、nested list flatten、日期驗證及 identifier 正規化。
- `ElasticsearchAdapter` 繼承 policy mixin，因此既有呼叫端仍由原 class/path 使用所有方法，不需改 API contract。

## 2026-08-20 ES model metadata security boundary

- `czjLLM/es_mode/model_metadata.py` 是 runtime model spec 與 ES metadata 之間的 allowlist/redaction boundary。
- `handlers.handle_data_mode._es_sink()` 只從 `ctx.model_spec` 投影安全欄位；兩個 ES sink 在 `_build_meta()` 最終寫回邊界再次遞迴移除 credential/model_spec/實際 endpoint URL，形成 defense in depth。
- pending/rerun policy 使用同一 `safe_model_tag()`，避免 rerun ES query 再帶入字串化 credential。

## 2026-08-26 ES bulk failure classification boundary

- `ESSink._flush()` 現在以單次 materialized actions 對照 bulk errors：成功 action 立即離開 buffer、可重試錯誤保留、ES mapping/parsing 400 永久錯誤移除。
- 永久 mapping rejection 轉為既有 `OutputProfileValidationError` 契約，讓 Row Merger 使用現有 terminal schema failure 流程釋放 row 狀態，避免相同 completed artifact 在 watchdog 中無限重送。

## 2026-08-26 multidim scalar type validation

- `multidim_event` output profile 在 ES sink 前強制 `Event[].consequence` 為 string 或 null，與 prompt 及 ES text mapping 對齊；結構化跨事件影響仍應放入 `Impact[]`。

## 2026-09-19 planned Reduction Engine v1 architecture

- 狀態：planned/approved architecture only；尚未實作。
- 新核心預計集中於 `czjLLM/reduction/`，包含 contracts/config/registry/engine/controllers/policies/execution budget/artifacts/executables/work units/manifests/reducers 與 source/sink adapters。
- Reduction Core 僅接觸 logical items、provenance、contracts 與 execution context；SQL/ES/TXT collection discovery 與 writeback 透過 adapters 隔離。
- `combine_utils.py`、`slice_merge.py`、live prompt-pipeline controller、Row Merger 保留 compatibility facade；`pipeline/merge/` 不納入 live Reduction Engine foundation。
- Worker 執行採 `Executable` 抽象，至少涵蓋 Task adapter 與 bounded PipelineRef adapter；Reduction Round 不等於 business Stage。
- Shared `ExecutionBudget` 必須先於 collection fan-out、semantic reducer fan-out 與 nested ReductionStage，且 child worker 不可另開不受控 pool。
- Collection Manifest 為 immutable/versioned contract，包含 stable member identity、ordering/window/watermark、lineage、contract version；aggregate output 使用 stable derived identity 與 idempotent sink upsert。
- SQL/Elasticsearch 為 multi-document collection 第一批 production targets；TXT/file 保留完整 single-document hierarchical reduction，collection 僅做 constrained manifest/adaptor。
