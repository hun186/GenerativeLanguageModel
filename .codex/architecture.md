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
