# Windows 單次啟動 GUI — 重大異常檢閱與管理

## 資料保存位置
- 復原安全狀態：各工作項目 `_extract_slice_identity/queue_recovery_status.json`。記錄 `blocked/incomplete`、原因、復查次數與是否需人工處理；此檔控制復原／寫回安全邊界。
- **新增**檢閱操作歷史：同一項目 `_extract_slice_identity/queue_review_actions.jsonl`。只寫固定代碼、操作 `open/ignored/resolved/deleted`、UTC Unix 時間與 `queue_modified=false`。不保存 Prompt、SQL/ES 回應、憑證、檔名或絕對路徑。
- 原有 `processing_quality` 稽核與 Load Meter 並不會因檢閱操作被刪除或改寫。
- 當工作因其他原因停止，檢閱歷史仍保留在其 item 目錄中；後續可由 GUI 手動選擇舊 item 目錄，或透過同次執行的 meter 取得。

## 開啟方式
Windows 的共用 `czjLLM/job_manager/win_gui.py` 進度 GUI 提供 **「⚠ 重大異常檢閱／管理」** 按鈕；所有使用此共用 GUI 的單次分析模式都能開啟相同的獨立 Toplevel 視窗。SQL／Table／ES 的啟動器在建立 Meter 後，自動把該次 Meter 路徑傳送給 GUI，避免掃描整顆硬碟。還可選 **「加入舊工作目錄…」**。

目前列表範圍：具有復原狀態檔的 Queue 重大事件，以及該次 Meter 中明確標示 `blocked_recovery`、`writeback_failed_schema`、`writeback_failed` 或 `recovery_incomplete` 的項目。沒有掃描完整歷史硬碟，也不宣稱可涵蓋所有非結構化錯誤日誌。

## 檢閱操作的精確語意

| 按鈕 | 操作效果 | 絕對不做的事情 |
|---|---|---|
| 重新整理 | 重新讀目前工作證據與檢閱歷史 | 不送出任務或修改檔案 |
| 已解決 | 只有不再處於 Blocked／證據不可讀／目前寫回失敗的條目，才能**結束檢閱** | 不代表 SQL/ES 寫回確認、不解除隔離、不清理 Success |
| 忽略 | 記錄操作員選擇忽略這次檢閱；異常仍顯示且執行完整性仍為 incomplete | 不設成功、不停止必要安全告警 |
| 刪除檢閱紀錄 | 記錄可復原的 `deleted` tombstone，對非活躍條目在預設清單隱藏；可切換「顯示隱藏紀錄」 | **不**物理刪除 JSONL、狀態檔或任何 Queue/Success/Prompt |
| 重新開啟 | 追加 `open` 記錄，恢復檢閱 | 不盲目重跑 LLM |

對仍在 Blocked、證據不可讀或仍有寫回異常的項目，即使按「刪除檢閱紀錄」，也應保持可見，不讓安全風險從檢閱畫面消失。

## 一鍵複製給 ChatGPT 除錯

在「重大異常檢閱與處置」視窗新增兩個按鈕：

- **「📋 複製選取條目（ChatGPT 除錯）」**：先點選一筆異常，再按此鍵，即可複製該筆診斷摘要。
- **「📋 複製目前顯示的異常摘要」**：一次複製畫面目前顯示的異常（最多 100 筆），包括顯示中的未結案條目；沒有資料時不清除剪貼簿。

複製後直接貼到 ChatGPT 對話。內容是固定白名單：異常代碼、執行狀態、檢閱狀態、來源列的已知錯誤代碼、復查次數、操作次數、是否需要注意，以及一段要求安全診斷的文字。未知或異常值一律以 `UNKNOWN` 取代。

**不會複製**：Prompt 原文、LLM 回應、SQL/ES 原始資料、主鍵、絕對路徑、檔名、日誌全文、帳號密碼、API Key、原始例外堆疊。這是為了避免貼到聊天時洩漏敏感資訊；若需要追查特定文件，請額外提供經人工確認、去識別化的診斷證據。

此操作**只使用本機剪貼簿**，不會自動上傳、呼叫 ChatGPT API、重新派工、修改來源 Queue/Success 或追加檢閱操作歷史。複製的狀態快照可能在之後發生變化；更新後請先按「重新整理」，再重新複製。

## 隔離復原與管理畫面的分工
- 只有 Queue 的安全復原演算法能改變 `queue_recovery_status.json`，而且仍要核對檔案身分、RUNNING／TODO 與復查上限；GUI 的任何檢閱操作都不會越過這個流程。
- GUI 的「已解決」只是**檢閱紀錄**結案，不是 LLM、整體批次或 sink 的成功。
- 異常檢閱沒有外部通知、跨專案中央資料庫或 Windows/SMB 生產環境安全解除；需要另行部署與驗收。
- Windows GUI 中掃描與列舉在背景 Thread 完成；Tk 控件只在原 GUI 進程主緒更新，避免卡住主進度畫面。

## 驗證及部署限制
PR #269 改變完整復原與 `full_restart` 安全條件；須在最新 HEAD 跑完 GitHub-hosted CI、正式 Codex Review，並經專案負責人明確批准 Merge。Hosted Tk 靜態/無螢幕測試不代表 Windows 真實 GUI 點擊、NTFS/SMB 競態、SQL/ES 寫回已通過；實機驗收依 Issue #266 執行。
