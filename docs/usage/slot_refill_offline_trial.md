# 動態空槽補位（離線驗證階段）

本階段新增 refill_scheduler.run_slot_refill 作為排程元件，
使用呼叫端提供的 claim_one、run_worker、acknowledge 三種回呼。
只有真正的前一筆完成且結果已由 acknowledge 確認，才會補下一筆；
不等待同一批中所有 Future 結束。max_inflight 是硬上限。

claim_one 必須透過既有 pick_and_claim_next_prompts 實際排他領取，
回傳真正的 Queue Claim 識別碼；回傳相同 receipt 會拒絕重複派工。
acknowledge 必須根據真正的 Success 防覆蓋／寫回確認判定完成。
工作例外、ACK 失敗、停止或 deadline 到期時，停止新派工，等待
已啟動工作安全收尾；不能自動把先前領取的檔案清空或重派。
這個元件**不呼叫 LLM、不修改既有 Producer/Consumer、Queue、
SQL/ES 及 GPU 配額**，目前僅以合成快慢任務／真實暫存
Queue Claim 檔案模擬驗證。沒有把它接入使用者的 Windows 生產派工。

示例（虛擬時間、兩個工作槽，耗時 10 + 七筆各 1 單位）：
傳統固定兩筆一批、等全批完成才下一批：13 單位；
有空槽立即補位：10 單位。這只展示 head-of-line barrier，
**不代表實際 GPU 使用率或 LLM 吞吐提升 23%**。

後續部署 Gate：接到真正 Consumer 的狀態與 Load Meter，
同時確認執行資源、Queue Claim 身分、Success/SQL/ES ACK
及 graceful drain；先在可停機的工作站影子模式比對，
確認沒有雙重推論、遺失任務及錯誤回補，再討論啟用。

## 2026-11-17 — Windows Legacy Consumer 接線（待驗收）

上述章節記載的是 #301 的歷史離線階段；本次 PR 將相同
`run_slot_refill` 原語接到 **Windows legacy single-stage**
`llm_stream_consumer`，不修改 Linux multiprocessing 或 stage-managed 模式。

- 保留既有 Consumer 的復原／空佇列／終止檢查；一次先真實 Claim 一個，
  再使用最多 `ctx.n_process` 個租用 worker 槽動態補入後續 TODO。
- 每筆 Worker 返回後需先驗證對應 `Success`，或明確恢復的 `TODO`；
  每筆獨立結算 `queue_running` 和 `rows[pk]` 的 Queue ACK，
  **然後**才填補空槽。單一慢請求不阻擋其他已成功結果。
- 原有 Row Merger 繼續等 `queue_pending=queue_running=0`；
  此處的 Success/Queue ACK **不是** SQL/ES sink confirmed-writeback。
  sink 的最終確認和來源保留條件不變。
- Receipt 缺失、Worker 無可驗證結果、Meter 更新失敗均採
  fail-closed，不製造成功計數或自動覆蓋 RUNNING/Success。
  使用現有 Consumer 終止/INCOMPLETE 協調及排錯流程。
- 動態補位只是送達 LLM 端點的 HTTP 請求，並未指定單一
  請求應到 GPU 0 或 GPU 1；GPU 與負載均衡需獨立驗收。
- 僅新增離線真實檔案 Queue 及 Meter 驗收；
  **Windows、Ollama H100、ES/SQL 寫回與長任務壓測均未實機驗證**。
  程式碼 PR/Hosted CI 不代表已在使用者的執行中 Job 熱替換。
