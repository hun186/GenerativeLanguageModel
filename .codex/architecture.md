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

## 2026-07-20 per-run LLM call audit

- `czjLLM.czjLLM_TextProcessing` 啟動後會建立一次性的 LLM call audit run metadata，掛在 `ctx.llm_call_audit_run_id` 與 `ctx.llm_call_audit_path`。
- `czjLLM/utilities/llm_call_audit.py` 是 append-only CSV audit helper，負責建立 `logs/llm_call_audit/llm_call_audit_<timestamp-pid>.csv`、維護 `latest_llm_call_audit.csv` 指標、解析 usage tokens 與 context limit。
- `PromptAPIPipeline` 在每次實際 `CallLLMAPI()` 成功後記錄 task、prompt file、model、endpoint、input/output/total tokens、context limit、context usage ratio、context exhausted flag、max_tokens 與 cost；呼叫例外時也記錄失敗 row（token 欄位為 0），方便追查中斷前最後一次呼叫。

## 2026-07-20 LLM context metadata resolution

- LLM call audit 的 context limit 不再由 model display name 推估；`llm_call_audit.resolve_context_limit()` 依序使用 response extension、Ollama `/api/show` model metadata、明確 `model_spec` 欄位，最後才回傳 unknown。
- `CallLLMAPI()` 在既有 token usage log 旁新增 context limit log line；token counts 仍取自 chat completion response `usage`，context limit 則來自模型 metadata 查詢或明確設定，兩者來源分開標示。
- Audit CSV 新增 `context_limit_source`，用於區分 `response`、`ollama_api_show`、`model_spec` 或 `unknown`，避免操作人員誤以為 context 是從模型名稱猜出。
