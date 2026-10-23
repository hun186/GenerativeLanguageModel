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
