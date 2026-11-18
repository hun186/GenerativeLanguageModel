# GLM JSON 修復差異：記憶體最近案例（PR #335）

## 目的與預設行為

本功能用於 **定性抽查 JSON 修復是否存在系統性問題**（例如只是補標點，
還是意外刪除 Event、時間與 Evidence 等資訊），不是為修復原文建立歷史資料庫。

- **Windows GUI：** 存放最近 **50 筆成功修復的原文／修復全文**，
  只存在獨立的 GUI 程序記憶體中，總預算 **16 MiB**、單筆 512 KiB
  且每側最多 80,000 字元；超過筆數或容量時自動淘汰最舊資料。
  個別過大、編碼不合法或 IPC 佇列滿載時跳過原文，不截斷或誤稱已保存。
- **Linux／無 GUI：** 沒有原文接收端。修復流程仍可記錄既有
  metadata-only Quality JSONL，程式不為此功能保存完整 JSON 原文。
- **原文預設不落地：** 普通 Log、Audit CSV、Quality JSONL、Queue
  及 ES／SQL 都不新增修復前後原文。既有數字、類型、字元變化與固定
  錯誤碼仍保留供後續量化檢查。
- **關閉 GUI：** 記憶體案例隨 GUI 程序終止消失；重新啟動無法還原，
  即使 Quality 記錄仍存在也是如此。
- **GUI 可顯示最近 50 筆 metadata 案例：** 同時以唯一的
  `run_id + event_id` 尋找記憶體全文。Quality 事件寫入成功且 GUI
  接收成功才可能查看完整對照；舊案例／被淘汰／背景執行／過載時
  會顯示明確「不可檢視」提示。

## Windows Worker → GUI 傳輸

GLM 使用執行緒處理 Windows 的一般 LLM Consumer；
Tk GUI 本身則是獨立的 `multiprocessing.spawn` 程序。
不能把 Worker 的 Python module-level List 當成跨程序資料庫。

因此 Worker 只在成功修復且 Quality 事件建立後，將單次修復 pair
送到 **獨立的 bounded private IPC 佇列**（最大 8 個待接收樣本）。
此 IPC 和 GUI 文字 Log／Quality 事件佇列是不同的：
GUI 程序收到後，在 Tk 執行緒內存入 FIFO，供原有 🔎 JSON 差異視窗
選取查看。傳輸失敗、過載、GUI 關閉或格式不合時，略過原文樣本，
絕不可延遲或改變 LLM 任務成功／失敗、重試、Queue ACK 與 ES 寫回結果。

這是抽樣診斷，不承諾每次修復都保存到 50 筆；若 GUI 在其他機器，
不會自動跨機器同步原文。沒有額外呼叫 LLM。

## 選用：原本的本機磁碟快照（明確 opt-in）

舊版 #335 的本機加密權限檢查／72 小時快取保留為**非預設選項**，
僅當操作員確實設定以下值時才會寫入磁碟：

```bash
CZJLLM_JSON_REPAIR_CAPTURE=1
# 可選：明確指定受保護的絕對私有目錄
CZJLLM_JSON_REPAIR_PRIVATE_DIR=/approved/private/json_repair
```

**不設定** `CZJLLM_JSON_REPAIR_CAPTURE`，或設為 `0`／`off`，
均不會寫入新的完整 JSON 快照。設定 `CZJLLM_JSON_REPAIR_PRIVATE_DIR`
**本身不會啟用寫入**。預設 Windows GUI 的記憶體查看不要求任何檔案目錄。

若選擇磁碟保存，預設路徑是已驗證的專案內
`.runtime-private/json_repair`，需通過原有 Windows 固定磁碟
NTFS／ReFS ACL、或 Linux allowlisted local filesystem 與
`0700` 目錄權限檢查。快照寫入需符合檔案安全及容量限制；
在啟動、下一次成功修復或 GUI 查看時 opportunistic 清理逾期 72 小時
檔案。停止程式／未執行清理時無定時 janitor。
檔案仍是**明文**，普通刪除不等於 SSD／備份安全抹除。
請排除專案備份、7z 部署包、雲端同步、共享硬碟及容器映像，
並獨立完成實機權限及資料留存驗收；缺少驗收不得在正式環境啟用。

若已在過去版本建立磁碟檔案，**關閉新捕獲不會立即刪除舊資料**；
啟動時仍嘗試清除逾期舊快照（必須先通過安全檢查），
必要時由管理者依本機政策清理。GUI 的「清除所選 Run 暫存」在
明確啟用磁碟模式時也會嘗試刪除該 Run 的磁碟檔案。

## 安全限制與驗收

- GUI RAM 暫存不代表 OS swap/pagefile、crash dump 或實機備份絕不包含
  記憶體。要處理高敏感資料，仍須主機層級控制。
- 記憶體與 Quality Log 的 join 僅供「同一 Run 的同一事件」對照；
  不保證來源語意真實、修復後原有事件完整性或 GPU／LLM 推論正確。
- 必須以最新 HEAD 的 Hosted Linux E2E、Hosted Windows Python
  3.10/3.11、changed-line Secret Scan、正式 Codex Review 零問題
  作為 Merge Gate。Self-hosted queued 不視為 PASS；
  GUI 視覺操作／Windows 工作站仍屬另行實機驗收。
- 本次不執行真實 ES／LLM／SQL、重新處理既有新聞或大規模修復。
