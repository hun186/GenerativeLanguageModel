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

## 2026-11-01 正式 Review 的 P2 修正
- 每列 last_state_at 是 Unix epoch seconds（例如 1793500000），**不能**套用只適用於切片數的 10^9 上限；已新增時間專用驗證與單元測試，合法時間正常顯示本機 HH:mm:ss。
- 執行中的 JSON Meter 若因資料破損或權限問題重試仍失敗，**絕不**降級成「0 列／0 異常」的正常快照。GUI 保留最後一次成功渲染的進度，並明示本次讀取失敗；讀取至多重試 5 次，防止持續卡住或誤導使用者。只對真正尚未建立的 Meter 顯示「尚未建立」。

## 2026-11-02 視窗排版與文字行高（待 PR 驗證）

- `Processing Quality／異常監控` 的品質摘要與主要錯誤清單依標題區寬度重新計算 `wraplength`，不再固定 720 像素，減少最大化視窗右側大片無效空白。
- `各列／文件進度` 使用獨立的 `DocumentProgress.Treeview` ttk style；從 Windows TkDefaultFont 的實際 `linespace` 計算列高（最少 28px，額外預留 10px），並為標題列增加 padding，避免 DPI 放大時文字頂端／底端被截斷。只調整展示；總列數、分頁、排序及 Meter 內容不變。
- `Cancel` 只發出取消事件並停用按鈕；工作流程仍採**合作式取消、安全收尾**，不強制 kill 正在處理的 LLM，也不能把取消請求視為 sink 成功。原取消事件與執行端行為均未修改。
- Headless 測試涵蓋 UI 建構結構與狀態分類；本機 Windows DPI 100%／125%／150% 仍需實際人工檢查（Issue #266）。

## 2026-11-02 每列新增模型／端點 IP 欄（待本 PR 驗證）

- 在「各列／文件進度」增加唯一一欄 **模型／端點 IP（已記錄）**，顯示例如 `qwen3.6:128k · 192.168.1.20:11434`，並加水平捲動讓縮小視窗／Windows DPI 放大時仍能查看。多組模型／端點時標示 `(+N 組)`；選取文件後，下方顯示最近有記錄的一組。與 `Running`、`Cancel`、Queue 及原先切片進度計算無關。
- **來源不是全域模型設定**。GUI 只在展開時，背景執行緒讀取「本次 Run」現有 `llm_call_audit_<run_id>.csv`，以 Audit 的 `prompt_file` 真正位於該 Meter row `item_dir` **目錄內**為依據，關聯 `model` 和 `base_url` 中的 IP literal。不同 item_dir 即使檔名相同也不混用。驗證須匹配完整路徑的目錄邊界，不猜 basename、文件數／切片數或 Worker 的全域模型。
- 顯示端點為 URL 中的**字面 IP 與可選 port**，絕不顯示 API key、URL userinfo、path、query、DNS hostname 或原始錯誤訊息。無法由 URL 直接辨識 IP、未完成 LLM 呼叫、歷史 Audit 沒資料或多階段無法匹配時，顯示 `—`／`IP 未記錄`，不進行 DNS 解析或額外模型呼叫。
- **重要時間語意：現有 LLM Audit 在實際呼叫結束後才寫入**。因此這是「最近**已記錄的**模型／端點」，**不是**當下正在飛行中的 Worker 即時 IP；若同一列在執行期間切換端點，可能顯示多組。呼叫失敗仍可能有已記錄的模型／IP，顯示它不表示呼叫成功或 SQL／ES 寫回確認。
- 唯讀解析沿用既有嚴格 Audit CSV 讀取器：單檔 16 MiB 上限、CSV 欄位完整性、檔案身分／非連結檢查。Run 太大、Audit 正在寫入而不完整、沒有 Audit 或格式不可信時，進度表與 Meter 仍可使用，模型欄顯示 `—` 並註明 Audit 暫無法核對，不以錯誤推測模型。針對超長 Run 的增量式證據索引應另行評估，不能無界讀取每筆日誌。
- 已新增實際 CSV／Meter 回歸測試，包含不同 Item 路徑、相似前綴、選擇多端點、URL 資訊遮蔽、遺失／截斷 Audit 與取消語意不變。Hosted CI 成功只能證明 headless 行為；Windows 100%／125%／150% DPI 實機互動及真實 Ollama／SQL／ES 還是 Issue #266 的獨立驗收。
