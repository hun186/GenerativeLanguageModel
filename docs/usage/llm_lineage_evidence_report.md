# LLM Audit 呼叫關聯證據（離線、唯讀）

這是既有 `llm_call_audit_<run_id>.csv` 的**單一 Run 證據覆蓋率盤點**，接續原有 Producer／Worker／Stage／Row Merger 異常觀測與追溯性待辦。它不連接 LLM、SQL、ES，不操作 Queue、Success，也不改變現有的 `llm_failure_report` 或 `processing_quality_report` 格式。

## 執行方式

在專案根目錄執行：

```bash
python -m czjLLM.cli_tools.llm_lineage_report --audit-path logs/llm_call_audit/llm_call_audit_<run_id>.csv
```

輸出僅為標準輸出的 JSON 統計。接受舊版不含 ID 欄位的 CSV；缺少的欄位顯示 `column_present: false`，其計數顯示 `null`，不會謊稱 0 個 Worker／Claim。已建立但未填入的 ID 顯示 `blank_rows`。

## 可供判讀的欄位

- `observed_csv_rows`：CSV 中的實際資料列，**不是** provider HTTP request 數、SDK 自動重試數或不重複的來源文件數。
- `audit_record_id`：現有的每筆 Audit 記錄 UUID4；同一 ID 重複出現在多筆記錄，屬於異常。
- `worker_call_id`：Worker 包裝器的本地呼叫 ID；可以在不同 CSV 列被引用，不預設它等於供應商的唯一請求。
- `queue_claim_event_id`：Queue Claim 觀測到的本機收據。此欄位只有部分路徑會提供；同一收據被多個 Audit 列引用，**不能**自動當成重複 LLM 呼叫或同一重試家族。唯讀報告不重新驗證實體 Queue 文件／收據。
- `call_llm_api_returned`：Worker 包裝器回傳 YES／NO 的可見證據；空白代表未知。即便回傳 YES，**也不等於 SQL／ES 已成功寫回**。
- `duplicate_rows`：同一 ID 在 CSV 中再次出現的列數；只有 `audit_record_id` 在本工具可被視為每列唯一性的破壞，Worker／Claim 的重複引用保留為觀察，不自動推論異常。
- `malformed_width_rows`、`invalid_rows`：CSV 欄數或 UUID 欄位不合規；遇到無法完整讀取的 CSV（末尾尚在寫入、鏈結／Junction、超出 16MiB）會中止報告，不輸出貌似完整的部分統計。

狀態 `observed`、`partial_evidence`、`degraded`、`no_rows` 只代表這份離線 CSV 記錄的證據情況。CLI 不輸出原始 UUID、文件主鍵、檔名、目錄、Prompt、LLM 回答、URL、錯誤文字、憑證。資料仍依既有 CSV 讀取器採用大小上限、不追隨連結與讀取期間身分驗證。

## 有意保留的限制

**此工具並沒有完成「權威 HTTP Request／Retry Family／文件分母」能力。** 真正的來源／世代綁定，需要 Producer、Worker 與呼叫層有具體且可驗證的生命週期／意圖／回執規格；現有的 `audit_record_id`、`worker_call_id` 和 `queue_claim_event_id` 不足以事後填補這種因果關係。即使 CSV `observed`，也可能漏掉錯誤前未寫入 Audit 的工作。請使用獨立 sink ACK／實際資料 readback 才能證明持久寫回。

新增回歸涵蓋實際臨時 CSV、舊格式、完整／欠缺 ID、合法共用 Claim、重複／格式錯誤 ID、欄數與狀態碼異常、非完整 CSV 及不洩漏原始資料；在 Hosted Linux CI 執行。真實 Windows／LLM／SQL／ES 驗收仍屬 Issue #266，不能由 headless 測試推定 PASS。
