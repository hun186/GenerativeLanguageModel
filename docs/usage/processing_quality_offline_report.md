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

The `--output` destination must be a separate normal `.json` report.
It **refuses** any filename in the reserved
`processing_quality_events_*.jsonl.manifest.json` namespace (including an
uncreated ledger or a ledger for another run), and it refuses symlink output
aliases. This prevents the generic atomic JSON writer from replacing a sealed
quality archive's SHA256 consistency ledger, which would otherwise invalidate
archived-run verification. A protected destination fails with a fixed error
**before** source replay or temporary SQLite indexing, without writing a
partial report. Ordinary reports such as `quality_summary.json` remain
supported and can be atomically regenerated. This guard does not make
concurrent writers safe or authenticate a ledger against malicious changes.

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

 
## 品質 JSONL 手動輪替與跨檔案報告重建（2026-10-24，獨立 PR 待驗）

第一階段採**人工停機、非自動、零刪除**模式，確保事件完整性優先於節省空間。務必先停止目前的 LLM/排程 Workers、寫入者及正在讀取品質資訊的 GUI，再執行：

```bash
python -m czjLLM.cli_tools.processing_quality_rotate --audit-path logs/llm_call_audit_<run_id>.csv --confirm-stopped
```

維護指令取得既有 JSONL 跨程序鎖後，只會把完整且以換行結束的 `processing_quality_events_<run_id>.jsonl` 以同目錄原子改名為 `processing_quality_events_<run_id>.jsonl.seg-00000001`（後續編號遞增）；沒有完整末行時直接拒絕，不會嘗試修補或截斷。正在使用中的活躍檔名保留為穩定位置，**下一筆事件將重新建立原活躍檔**。最多支援 64 個輪替分段，滿額時拒絕而不刪舊檔；可使用 `--max-segments` 設定更保守的上限。預設**不排程、不自動輪替、不清理、不覆寫**。

既有 `processing_quality_report --audit-path ...` 與 `--audit-dir ...` 離線報告可依分段編號順序重新讀取整個單次執行的封存檔和活躍檔，使用**同一份**事件累計器進行跨段 `event_id` 去重、Schema 失敗與後續寫入成功之回復統計，保留原 `incident_diagnostics` 及分母語意。封存檔即使尚無新活躍檔，仍可被歷史報告發現。缺少中間編號、封存名稱異常、分段超限都會拒絕當成完整報告；封存檔末尾不完整會顯示 `degraded_incomplete_archive`，不會冒稱成功。原 `log_file` 欄位仍只提供穩定活躍檔 basename。

**限制**：目前並未提供封存資料完整性 Manifest，無法證實最後一段或整批封存資料是否遭到人為全部移除。檔案仍可能受未遵守停機要求之外部寫入者干擾；停止所有 Worker/GUI 是操作條件。現行即時 GUI `QualityTailReader` 仍主要追蹤活躍單檔，輪替後的跨段完整計數請以離線報告為準。自動保留／空間預算清理、可證實不遺失事件的持續性續讀（含即時 GUI）、Manifest、跨日滾動窗口都尚未完成，需獨立設計並複審，不應自行刪除封存檔。


## JSONL 封存完整性 Manifest（2026-10-24，獨立 PR 待驗）

本功能不變更既有手動輪替指令的預設行為。**沒有 Manifest 的歷史封存仍可閱讀，但離線品質報告新增 `archive_integrity.status=unsealed_legacy`，明確表示未具備雜湊基準。** 沒有封存資料時為 `not_applicable`。即使離線報告顯示 `state=observed`，也不代表歷史封存已經驗證。

首次封存後，先停止所有寫入者、Workers 與品質 GUI 讀取，再進行一次性基準建立（trust on first use）：

```bash
python -m czjLLM.cli_tools.processing_quality_manifest --audit-path logs/llm_call_audit_<run_id>.csv --initialize --confirm-stopped
```

此命令只對**當時已存在的編號封存分段**計算 SHA-256、檔案長度與序號，將無原始事件內容的 `.jsonl.manifest.json` 安全落地，已存在的基準不得默默重新建立或覆寫。後續停止 Workers 後執行既有 `processing_quality_rotate ... --confirm-stopped`，若已有 Manifest，會先核對所有舊封存，再於成功輪替時一併擴充 Manifest；Manifest 發布失敗時，在同一輪替鎖內嘗試恢復活躍檔名，**不自動丟棄原始資料**。

唯讀驗證可隨時執行：

```bash
python -m czjLLM.cli_tools.processing_quality_manifest --audit-path logs/llm_call_audit_<run_id>.csv
```

既有 `processing_quality_report` 單次與歷史報告會於重建前後核對 Manifest。封存檔雜湊或份數不符、Manifest 格式毀損、缺少已封存的最高編號、封存內容在讀取期間變動時，直接拒絕提供看似完整的報告，不靜默重新歸零。Manifest 只記錄 `schema_version`、`segments[].{sequence,bytes,sha256}` 與 `ledger_sha256`，不含來源文件、Prompt、模型端點或原始錯誤內容。

**安全邊界與保留限制：** SHA-256 側錄可檢出意外覆寫、損毀及建立基準之後的封存檔遺失，但不具備數位簽章／外部信任錨；有權修改所有檔案的人仍可重算 Manifest，若連 Manifest 也被移除就無法單憑本地目錄證明歷史曾存在。首次建立基準只能證實*當下*現存封存檔，不能追溯先前是否已有缺失。活躍 JSONL 不受封存 Manifest 保護，需先手動輪替才能封存驗證。停機確認是操作者責任，不能防止不遵守規則的外部修改。仍**沒有**自動清理、已驗證安全刪除、線上無停機輪替或跨段 GUI 即時續讀；這些須另外設計及審查。


## GUI 跨輪替 JSONL 累計續讀（2026-10-24，獨立 PR 待驗）

Processing Quality GUI 背景品質讀取器改用 `QualityRunTailReader`。對單一 run 的品質事件，先核對已封存的所有連續編號分段與 Manifest（若已封存），以**同一份累計器**跨封存檔和活躍檔重建事件、文件 Schema 待處理與後續寫入成功數；當分段與基準不變時，僅增量處理活躍檔**新增的完整 JSONL 行**，不會每秒重新雜湊或讀取全部歷史分段。若檔案被手動輪替、活躍檔重建／截斷，會重新建立同一執行的歷史統計，而不是僅顯示新活躍檔的事件數，也不會直接把不同檔案的統計相加造成重複計算。

GUI 主執行緒只接收背景執行緒回傳的彙總資訊，不在 Tk 執行緒讀取大型 JSONL，也不回傳 document ID、Prompt、模型回應、端點或原始事件。面板在歷史封存尚未建立 SHA-256 Manifest 時標示「歷史封存未建立完整性驗證基準」，遇到損毀完整紀錄、末行只寫了一半時也有不同警語。若發現已驗證封存缺失、雜湊改變、未知替換或不安全路徑，**顯示「品質事件封存或檔案驗證異常，統計暫不可用」**，不再展示上一次可能過時的正常事件百分比。

此處的「續讀」是**在同一 GUI 執行期間**基於輪替代數和完整事件的恢復；單次啟動時必須載入當前 run 的既有封存，且初次載入成本與檔案總量成正比。封存的 inode／長度／mtime 或 Manifest 的 Metadata 改變才會重算 SHA-256；穩定期間採 metadata 檢查與活躍檔 tail，不提供惡意對手同時竄改檔案及偽造 timestamp 的即時防竄改保證。完整檔案驗證的正式來源仍是離線報告。

**重要：現行手動輪替仍要求先停止所有 Worker 與 GUI。** 測試是在兩次讀取之間模擬輪替與 GUI 再啟動／恢復讀取，不代表已支援無停機線上輪替。Windows Tk 視覺呈現、自動清理、安全跨進程協作以及惡意改寫偵測需獨立驗收；Linux Hosted pytest 不代表 Windows 真機完成驗收。


## GUI 大型品質紀錄安全預算（2026-10-25，新獨立 PR 待驗）

為防止單一極大型 run 讓 Tk GUI 背景讀取器無限制保留唯一事件 ID、文件決策身分與超長 JSONL 單行，新增僅套用於 GUI 跨分段讀取器的**非破壞性安全預算**：每 run 最多接受 `50,000` 筆唯一事件、累計至多 `4,000,000` 個被保留身分字元（事件 ID 及首次遇到的文件 ID），單筆原始 JSONL 完整行不得超過 `65,536` bytes。這些是保守的基數／資料讀取安全門檻，**不等於精確 RSS RAM 上限**；如遇特殊字元、Python 物件額外配置、GUI 首次歷史重建、其他應用負荷，實際總記憶體使用仍不同。

任何安全預算超限時，**不得**將後續事件直接略過、裁切事件 ID、簡化文件集合，或繼續以局部統計宣稱完整；GUI 改為顯示「⚠️ 品質事件超過 GUI 安全累計上限，統計暫不可用；請使用離線報告」，事件數值清為不可用狀態。不修改 JSONL 事件流、封存、Manifest、寫入者或既有離線 CLI。安全界線是讀取端的明確 fail-closed，不是自動分段、資料保留、刪除、重新建立基準或降級精確度。

`QualityAccumulator` 可選用 `max_events` / `max_identity_chars`，而 `QualityTailReader` 可選用 `max_line_bytes`；缺省值仍維持既有不設上限的完整離線報告與回歸測試契約。`QualityRunTailReader` 建立 GUI 專用讀取器時套用三個門檻，跨所有封存與活躍檔使用同一份預算。任何超限在變更事件計數器**之前**拒絕，並保留被拒絕那一筆事件的讀取起點，避免隔次輪詢錯誤跳過。安全預算對 GUI 連續讀取生效；仍需對超大型離線報告個別評估效能與可用 RAM。將來如需處理超過 GUI 限制的所有事件，須另外設計可驗證、具明確成本與復原機制的精確磁碟檢索／checkpoint，不能在本功能內偷偷丟棄唯一 ID 或已觀察到的文件狀態。

**驗證限制：** 自動化回歸覆蓋真實 JSONL 追加、跨封存基數、單行過大、身份預算、背景 GUI thread 告警與切換 run 後恢復，Linux Hosted CI 不能代表 Windows Tk 視覺驗收。手動輪替仍需先停 Workers／GUI，自動保留與刪除仍未開啟。


超限來源如果在 GUI 輪詢期間持續未改變，讀取器會快取**失敗檔案世代的檔名與有限 stat 身分資料（封存、Manifest、活躍檔）**，維持 `capacity_exceeded` 狀態，不再於每次輪詢重播整段 JSONL 或重算封存 SHA-256。只有檔案世代的身分資訊發生變更，才重新嘗試；切換 run 會建立新讀取器。快取不儲存敏感事件內容或成功統計，也不能把容量超限錯誤降級為正常統計。若歷史封存檔在這次工作階段曾被觀察到，即使是在首次超限的讀取過程中，之後突然減少也必須回報完整性異常，避免顯示誤導性的較小累計值。這是有限 metadata 偵測的效能設計，不提供惡意偽造 mtime/大小時的即時完整性保證。


注意：超限世代的「避免重掃描快取」與「本工作階段已觀察到的檔案存在紀錄」分開管理。即使因為同時讀寫、metadata 競態而取消超限快取，已經看過的歷史封存數量與活躍檔仍不能悄悄消失。活躍檔被移走，必須能由新增且同一檔案身分的封存分段解釋。反之，驗證失敗的陌生封存／Manifest 不會自動變成已接受的歷史基準，以避免修復臨時錯誤後仍無法恢復正常統計。此功能仍不授權線上輪替。


## 手動輪替中斷後的保守復原（2026-10-24，獨立 PR 待驗）

當已建立完整性 Manifest 的單次執行，在 JSONL 封存名稱轉移完成、Manifest 尚未完成發布的狹窄中斷窗口內停止，目錄可能存在比 Manifest **恰好多一份**連續編號封存、原活躍檔案消失的狀態。此時原有報告依規定拒絕宣稱封存已驗證；不可直接重新 `--initialize` 覆蓋基準。

先執行完全唯讀檢查：

```bash
python -m czjLLM.cli_tools.processing_quality_recover --audit-path logs/llm_call_audit_<run_id>.csv
```

回報 `verified`、`rollback_candidate`、`ambiguous_active_present`、`unsealed_legacy` 或 `not_applicable`，並只提供已封存、現存封存份數與活躍檔是否存在，不顯示任何原始日誌、文件 ID、Prompt、錯誤文字或絕對路徑。`rollback_candidate` 只表示**已驗證 Manifest 原有封存全部完整，另外恰有一份內容完整、末行換行的未受保護封存，且活躍檔不存在**；它不證實最後一份資料必然由中斷輪替產生，亦不證實其中每個事件都有效。

經操作者另行確認所有 Workers、排程及 GUI 已停止、檢查現場與備份後，才可明確執行：

```bash
python -m czjLLM.cli_tools.processing_quality_recover --audit-path logs/llm_call_audit_<run_id>.csv --rollback --confirm-stopped
```

使用相同寫入鎖，僅在 `rollback_candidate` 可復核成立時，把那份**尚未納入 Manifest**的分段內容恢復成活躍 JSONL；不修改已有 SHA-256 Manifest、任何先前封存，也不覆寫已存在的活躍檔。為避免競爭覆寫，復原時使用排他硬連結建立活躍名稱，檢核相同 bytes 後，才移除原先**未封存完成**的額外名稱。復原前（唯讀檢查及持鎖復核）會拒絕已存在其他 Hardlink 的額外候選檔（`st_nlink` 必須恰為 1），避免原封存或其他檔案的 inode 被恢復為可寫 active；新建立的 active 與候選檔必須恰好形成同一 inode 的兩個連結，否則保留兩者供人工處理。若檔案系統不支援硬連結便拒絕作業；若兩步驟間再度中斷，可能留下兩個指向相同資料的名稱，系統會回報 `ambiguous_active_present`，要求人工判斷而不清除任一檔案。成功回報 `rolled_back_to_active_unsealed`，代表新增檔案回到**未封存活躍狀態**，後續再由原本的手動輪替流程封存並將摘要加入 Manifest。

**拒絕自動復原**：Manifest 遺失或損壞、已封存的任一檔案雜湊不符、缺少既有封存、多於一份額外封存、活躍檔同時存在、符號連結、未確實停止讀寫程序等。工具不會由未驗證額外封存重算或直接延伸 Manifest，也不會自動刪除已封存資料。這是經人工作業隔離下有限且保守的復原流程，**不是**自動當機修復、全面斷電一致性保證，也不能取代備份／外部可信驗證。GUI 跨段讀取已另行實作，但仍要求停止相關 Workers／GUI 進行手動輪替；自動刪除與清理仍未開啟。
