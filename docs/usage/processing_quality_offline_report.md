# Processing Quality: offline per-run reports (PR after #218)

This tool reads the **existing** logs/llm_call_audit/processing_quality_events_<run_id>.jsonl.
It does not call LLM/Ollama, a database, or network, and does not generate another audit stream.
It does not modify either the original llm_call_audit CSV/XLSX or the quality JSONL.

Use one specific run (the matching CSV need not itself exist yet, as long as its JSONL exists):

    python -m czjLLM.cli_tools.processing_quality_report --audit-path logs/llm_call_audit/llm_call_audit_20261020-123456-123.csv

List at most 20 latest quality run files from the same directory:

    python -m czjLLM.cli_tools.processing_quality_report --audit-dir logs/llm_call_audit --limit 20

Write a separate **summary JSON**, atomically:

    python -m czjLLM.cli_tools.processing_quality_report --audit-dir logs/llm_call_audit --output quality_summary.json

The percentages and counters reuse QualityAccumulator, including de-duplication and recovered-schema semantics; source event records/document IDs are not exported. Unknown denominators show null, not 0%. Each denominator under 30 adds an **advisory only** (not a statistical pass/fail gate). The reports never combine numerators/denominators across runs.

A partial trailing JSONL record is ignored until complete, and reported as incomplete_or_concurrent_append; the file may be actively appended during inspection. Malformed complete UTF-8/JSON lines are excluded from denominators but counted in `skipped_corrupt_complete_lines`; the state becomes `degraded_corrupt_lines` even when other valid events exist. This is a completeness warning, not a forensic reconstruction of damaged content. Invalid-schema JSON records and duplicate event IDs continue to use the existing reader policy.

Confirmed writeback applies only to explicit Sink acknowledgement (currently ES bulk, not ES read-after-refresh). A missing confirmation for Excel/CSV is **unknown**, not failed. A document-schema pending percentage only covers observed, decided documents, not all scheduled documents.

The user must still perform a small real Windows + LLM + ES acceptance run for merged PR #218. Keep this new report PR unmerged while using the pinned #218 merge commit for that acceptance.

The quality tail reader also counts **schema-invalid but JSON-decodable complete lines** as degraded, while duplicate event IDs remain deduplicated without being labeled corrupt. For replaced files the reader resets when the inode changes, processed prefix/tail changes, or the file shrinks. This lightweight bounded fingerprint detects common truncate+rewrite patterns but is not a cryptographic guarantee against a same-size rewrite that leaves both sampled ends unchanged.

A duplicate is harmless ONLY when the same `event_id` replays an identical canonical complete JSON event (independent of object key order). A conflicting record reusing the ID is degraded corruption. If the input file generation changes, `QualityTailReader.poll()` returns `changed=True` even when the replacement is empty or all-invalid so the GUI does not retain stale totals.

Strict JSON parsing now rejects non-RFC constants (NaN, Infinity, -Infinity) that Python accepts by default. Event IDs must contain non-whitespace characters; document IDs must likewise be nonblank. Even when called with in-memory mappings, the accumulator rejects non-finite extra numeric values instead of generating a misleading accepted event. Such records degrade the offline report and never enter its denominators.


## Consumer 調度異常稽核（2026-10-23）

舊版單階段 Consumer 批次超時、批次例外或未捕捉例外退出時，沿用既有 quality JSONL 寫入 `consumer_orchestration_failure`、`scope=run`，僅允許 `CONSUMER_ROUND_TIMEOUT`、`CONSUMER_ROUND_EXCEPTION`、`CONSUMER_TERMINATED`。新事件不包含原始例外訊息、文件 ID、Prompt 或路徑；稽核失敗不改變既有重派／中止流程。

GUI 與離線報表 `consumer_orchestration_failure_events` 是**觀測到的調度事件次數**，重試可能多次計入；不是呼叫、切片、文件失敗數，也沒有百分比分母。原有百分比分母不變。本階段尚未涵蓋多階段 Stage Worker、Producer 或 Row Merger 一般例外，也不代表實際 Windows／LLM／ES 驗收通過。

## Row Merger 暫時寫回異常觀測（2026-10-23，後續獨立 PR）

Row Merger 在非 Schema 的可重試例外路徑，使用既有稽核 JSONL 新增 `row_merger_retryable_failure`、`scope=run`，只接受 `ROW_MERGER_PREPARE_RETRY`（寫回準備階段）和 `ROW_MERGER_WRITEBACK_RETRY`（開始寫回後的 Sink／確認階段）。事件不含文件／切片 ID、原始例外訊息、URL、Prompt 或結果內容。寫入失敗為 best effort，不改變原有 pending、ES buffer discard 或重試行為；具體異常仍看原系統操作日誌。

為避免每 0.5 秒 Watchdog 重試就寫入事件，**只在原有同筆錯誤的日誌節流窗口觸發時記錄**。因此 `row_merger_retryable_failure_events` 與 GUI「Row Merger 暫時異常」表示**節流後觀測事件數**，不是所有實際重試次數、失敗文件數、API 呼叫失敗數或永久寫回失敗率。相同筆數後續重試成功，不會抵銷已發生的運作異常事件。Stage 尚未準備好、文件 Schema 終止、合作式取消均不列入此類事件。

同一品質 JSONL 中仍採不同分母：slice JSON 嘗試、repair 嘗試、已判定 document、run 調度事件。本次只補 Row Merger 的非 Schema 例外；Producer、Stage Worker 尚未納入。Windows self-hosted Runner 未部署，需保留實機驗收待辦，不得以 Linux 離線 PASS 推論 Windows／Ollama／ES 實際資料寫回驗收完成。

### PR #223 初輪複審與驗測修正

原本僅在寫回主體例外 handler 發送可重試事件，漏掉 `_resolve_combined_path` 將 `combine_api_finished_item()` 一般例外捕捉後返回的準備階段重試。現改為兩個路徑共用節流的 run-scoped emitter，不改變當次 retry、Success 保留或 cancellation 流程。另明確區分「失敗嘗試」和「之後成功且由 Sink 確認的文件寫回」：兩種事件可同時存在，不能將 quality JSONL 總事件數當成重試事件數。新修正仍須 exact-head Hosted Linux CI 與 Codex 複審通過。

## Producer 操作異常稽核（2026-10-23，獨立待驗 PR）

Producer 原有三種「已捕捉並可繼續處理」的非 Schema 操作例外，會寫入現有每輪 Processing Quality JSONL 中的 `producer_operational_failure` / `scope=run`：`PRODUCER_SCHEDULE_EXCEPTION`（`schedule_one_row()` 丟出非取消例外）、`PRODUCER_BACKPRESSURE_EXCEPTION`（backpressure 等待拋出非取消例外）、`PRODUCER_FUTURE_EXCEPTION`（多階段 row Future 的 `result()` 丟出非取消例外）。事件不含文件／切片識別、來源、例外文字、Prompt、URL 或路徑；記錄失敗不改變原本的排程、釋放及中止行為。

GUI「Producer 執行異常」及離線報表 `producer_operational_failure_events` 是已捕捉例外**事件次數**，不是不同失敗文件數、API 呼叫失敗數或一輪排程的完整失敗率。單一 row 也可能發生多次操作異常；正常 pending 跳過、任務數為零、合作式取消不列入此事件。Stage Worker 內部一般錯誤並不等同 Producer 的三個邊界，將由獨立階段擴充。

本次僅在 Hosted Linux 與離線回歸測試範圍內驗收；Windows self-hosted Runner 未架設，實際 Ollama／SQL／ES 寫回與 GUI 視覺驗收都仍須操作端安排。

### PR #224 初輪複審分類修正

`PRODUCER_SCHEDULE_EXCEPTION` 僅在 `schedule_one_row()` 本身丟出非取消例外時記錄。前後的 Pending Console `mark_running`、紀錄更新、schedule-noop 釋放錯誤並不是 scheduler 的錯誤，**不可以套用這個代碼**；其具體問題仍由原有的操作日誌與排程錯誤處理承擔，不是本階段 Producer 監控全面涵蓋的範圍。新增防止這三類誤判的回歸測試；本變更需對新 Head 重新跑 Hosted CI 與正式 Codex 複審。

### PR #224 第二輪 P2：取消流程與品質計數

多階段平行 Producer 的 `schedule_one_row()` 若觸發 `ExecutionCancelled`，清理 Pending Running 狀態與寫入取消異動紀錄都屬於「盡力而為」，即使這兩者失敗也**必須保留原始取消訊號**。原始取消仍由 Producer 記錄 `_producer_cancelled=True`，不得誤記為 `PRODUCER_FUTURE_EXCEPTION`。新回歸測試會確認單一或兩個清理操作同時失敗時仍有正確取消結果；Host Linux CI 和正式 Codex 複審以最新 PR Head 為準。

## Stage 調度例外監控（2026-10-23，獨立待驗 PR）

Stage 管理的多階段流程在**真正的階段任務解析與輸入準備**拋出例外時，記錄 `STAGE_PREPARE_EXCEPTION`；在 Stage Runner 呼叫（含既有雙參數相容回退）最終拋出例外時記錄 `STAGE_RUNNER_EXCEPTION`。共用 Processing Quality run-scoped JSONL，只存固定代碼與最少的執行資訊，不存切片／文件識別、階段名稱、例外文字、Prompt、輸出、檔案路徑或模型端點。稽核寫入失敗不會替代原本的例外，`ExecutionCancelled` 不算失敗。

GUI「Stage 調度例外」與離線 `stage_orchestration_failure_events` 表示例外**事件數**，不代表各文件失敗次數、某階段失敗率或實際 LLM API 失敗率。Runner 的內部可能是 LLM、檔案或其他操作，因此單憑此事件不能判定根本原因為「非 LLM」。Runner 正常回傳 `ok=false`、路由未命中、雙參數相容回退成功，均不列入這個例外觀測。Stage 結構外的獨立 Worker 與持久化的失敗分類仍須獨立處理；Windows／真實 ES／Ollama 驗收暫緩。

## Leaf Worker 執行階段例外分類（2026-10-24，獨立待驗 PR）

Leaf Worker `PromptAPIPipeline.proc()` 在已捕捉的非取消例外處，依**實際執行位置**寫入現有每輪 Processing Quality JSONL：`WORKER_PRECALL_EXCEPTION`（挑選端點／呼叫前準備）、`WORKER_LLM_CALL_EXCEPTION`（執行 `CallLLMAPI()` 呼叫時）、`WORKER_RESPONSE_EXCEPTION`（取得呼叫結果後，回應解析、JSON 驗證與後處理）、`WORKER_PERSIST_EXCEPTION`（儲存 Success 或身分紀錄）。事件為 `worker_phase_failure` / `scope=run`，只帶固定類別，不包含文件／切片／階段身分、Prompt、回應、原始例外文字、儲存路徑或端點。取消、正常完成、未拋錯的 `ok=false` 結果、測試用 Mock 執行不會被算作新 Worker 例外。

GUI「Worker 階段例外」與離線 `worker_phase_failure_events` 為事件數，**不表示失敗文件數、失敗 API 呼叫數或遠端服務故障次數**。`WORKER_LLM_CALL_EXCEPTION` 只證明例外發生在 `CallLLMAPI()` 呼叫點，不代表可以認定模型伺服器有錯。LLM 呼叫 CSV 的既有逐次紀錄與 Worker 事件可能對應相同失敗，禁止把兩者相加。這一輪不變更 Worker 的原有錯誤回傳、CSV 稽核、retry 或取消語意；稽核 JSONL 寫入失敗仍不影響既有回傳。

這次範圍不涵蓋 Worker 進程突然中止、未拋例外的語意失敗、真實 Windows／Ollama／Elasticsearch 已驗收，亦不宣稱已建立完整的 Worker 根因分析。相關事項需獨立工項及實際執行證據。

## OpenAI SDK 類型化呼叫失敗原因（2026-10-24，待驗獨立 PR）

原 `worker_phase_failure` 的 `WORKER_LLM_CALL_EXCEPTION` 泛用分類，現在只在可由 SDK 型別或其既有保留的直屬例外原因證實時，細分為 `WORKER_LLM_TIMEOUT_EXCEPTION`（逾時）、`WORKER_LLM_CONNECTION_EXCEPTION`（連線）、`WORKER_LLM_RATE_LIMIT_EXCEPTION`（429）、`WORKER_LLM_HTTP_SERVER_EXCEPTION`（HTTP 5xx）、`WORKER_LLM_HTTP_CLIENT_EXCEPTION`（HTTP 4xx）以及 `WORKER_LLM_RESPONSE_VALIDATION_EXCEPTION`（SDK 回應驗證）。其餘維持泛用代碼，不從原始例外文字、端點或模型內容推論。逾時／連線可能是客戶端問題；收到 HTTP 5xx 並不等於證明模型推論故障。

**仍然每個已捕捉 Worker 例外最多只寫入一筆既有 `scope=run` 事件**，不另外計一個 SDK 事件、不變更 CSV 稽核或 `worker_phase_failure_events` 分母，不存原始例外、Endpoint、Prompt、來源識別、機密或輸出。SDK 可能先重試數次網路請求才將例外交給 Worker，品質事件數不代表底層 HTTP 嘗試次數或失敗文件數。取消流程、Mock-only 及原先的 Stage／Producer／Row Merger 事件分類不受影響。Hosted Linux 模擬 HTTP 傳輸測試不能取代真實 Windows／Ollama／Elasticsearch 驗收。


## 執行層級異常診斷與分類篩選（2026-10-24，獨立 PR 待驗）

`python -m czjLLM.cli_tools.processing_quality_report --audit-dir logs --limit 20 --incident-family worker_phase_failure`

或針對單次執行使用 `--audit-path logs/llm_call_audit_<run_id>.csv --incident-family stage_orchestration_failure`。`--incident-family` 僅允許本系統固定的 `scope=run` 異常類別：`consumer_orchestration_failure`、`row_merger_retryable_failure`、`producer_operational_failure`、`stage_orchestration_failure`、`worker_phase_failure`。未指定時顯示全部異常類別；指定時僅縮減 `incident_diagnostics.families` 顯示內容，**保留完整 `metrics` 與該次執行全部執行層級事件的分母**。未知、文件或切片類別不會被默默當成零事件。

報告的 `incident_diagnostics.observed_run_incident_events` 是經既有 JSONL 驗證器接受、去重後的**執行層級事件數**；`share_of_observed_incidents_pct` 是各類事件在當次觀測的相對占比，**不是 LLM 呼叫失敗率、失敗文件率、獨立錯誤根因數或 ES 寫入失敗率**，同一實際故障可能先後在 Worker、Stage、Producer 被不同捕捉點觀察到。分母為零時百分比為 `null`（未知），樣本少於 30 時提示低樣本警語。歷史報告維持每次執行獨立統計，不合併分母；原始 JSONL、Prompt、來源身分、端點、密碼、錯誤訊息均不會出現在新的診斷欄位中。

若既有 JSONL 含格式損毀完整行，或尾端只有部分寫入，維持現有 `degraded_corrupt_lines`／`incomplete_tail` 狀態，不能因顯示有分類而視為驗收成功；此功能無模型端點、資料庫或網路需求。既有報告 `log_file` 檔名欄位仍存在，執行 ID 不應含私人資訊。
