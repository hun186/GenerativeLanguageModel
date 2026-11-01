# Windows GUI：可收合的各列／文件進度

## 功能
共用 Windows 單次執行 GUI（czjLLM/job_manager/win_gui.py）新增預設收合的「▶ 各列／文件進度」區塊。展開後使用本次 Run 的 Load Meter 顯示每列：
- 列／文件 ID（Meter row key）。
- 當前階段：切片等待、LLM 執行中、切片完成待合併、多階段處理、待寫回、Row Merger 已標 merged、隔離或失敗等。
- 切片進度：10 格圖形文字進度、百分比、done/total。
- 等待／執行切片數：queue_pending 與 queue_running。
- 最後更新時間：從 scheduler、dispatch、finish/requeue 順便存入的 last_state_at 格式化為本地時間 HH:mm:ss；舊資料缺少顯示「—」。

**重要：切片完成 100% 不等於 SQL/ES 寫回成功**。merged 是現有 Row Merger 的狀態標記，不代表獨立 sink readback。

## 篩選與效能
- 預設「目前處理」顯示進行中和異常；「異常」只顯示明確失敗；「全部」含完成紀錄。
- 可輸入列 ID 搜尋並按 Enter；每頁 12 列，提供上一頁、下一頁及手動更新。
- 按優先順序排序異常、執行中切片、多階段、待寫回、等待中。
- 收合時不讀取；展開後透過背景執行緒每約 1.5 秒唯讀 Meter；同時僅允許一個讀取工作，Tk 主執行緒只渲染目前頁。
- 若 Meter 超過 12 MiB、非一般檔案或包含不安全連結，顯示讀取問題，不截斷後假裝正常。
- 目前會提供 Run Meter 的 SQL／Table／ES 等模式直接適用；未提供 Meter 的其他單次模式會明確顯示尚未收到資料，而非推測逐列進度。

## 重大事件檢閱與時間線修正
- 重大事件檢閱改為每頁 100 候選條目、已知失敗優先，跨頁檢查；不再因超過 500 個工作直接拒絕整批。
- LLM Audit 新寫入的時間帶本機 UTC offset。既有不帶 offset 的歷史紀錄會標為「本機時間、時區未知」，不得當作 UTC 插入時間線。

## 驗證
本 PR 需要 exact-head Hosted Linux / Windows CI、正式 Codex Review、安全掃描與 owner 明確 Merge 授權。Headless 單元測試不等於 Windows GUI 125%／150% DPI、NTFS/SMB 或真實 LLM/SQL/ES 寫回驗收；相關 Issue #266 仍需 operator 實機驗收。
