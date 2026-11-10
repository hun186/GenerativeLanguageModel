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
