# Queue Blocked 自動追蹤與安全復查（PR #269）

## 原則

- **Blocked 並非完成或丟棄**：原始 TODO、RUNNING、Success 全部保留，不自動清空、不執行 `full_restart`、不根據時間直接重跑 LLM 或 SQL/ES 寫回。
- **正常工作繼續**：Consumer 只隔離受影響的 item；Producer 背壓將已隔離且仍計入原始負載的來源另外列出，避免阻擋之後的健康 rows。原始 queue meter 不會虛報完成。
- **有界追蹤**：預設 30 秒冷卻、每項最多 5 次復查；達上限後停止主動嘗試，保留 `operator_required` 狀態、Load Meter 和固定代碼稽核事件。
- **極窄的安全自動解除**：僅支援可核實原始 RUNNING 正規檔案已由其他安全執行者移到 TODO、inode/大小/mtime/相對路徑完全相符，且 RUNNING 已空、Success 不衝突、兩次冷卻間隔快照一致。*不*由復查工具自行移動、重新切片、清除或重送 RUNNING。POSIX 有相關安全能力時才嘗試；Windows/SMB 未經正式驗收，不自動解除。
- **不能證明安全**：名稱衝突、未知檔案身分、損毀 marker、未驗證寫回或多來源等，繼續隔離，將復查次數與原因提供管理員確認，不自動重建、不假裝已完成。

## 作業方式

在使用中的 Consumer 會定期安全復查；生產者尚未結束時，即使當前 registry 全為 Blocked，也會保持可接收新的健康 rows。當本次 Producer 結束，Consumer 會回報整批 `incomplete` 而非成功。

需要在主任務已退出後**持續復查**時，可由部署環境排程執行下列有限任務（例如使用 Windows 工作排程器、cron 或 systemd timer），或以前景 `--watch` 模式操作；**程式不會自己秘密建立常駐服務、外發通知或雲端排程**：

```bash
python -m scripts.recheck_queue_recovery --item-dir "/data/prompt/item-dir"
python -m scripts.recheck_queue_recovery --item-dir "/data/prompt/item-dir" --watch --interval 30 --max-rounds 5
```

多項目可重複指定 `--item-dir`；最多 100 項。輸出只包含 item 序號、狀態、復查次數、整體結果，不包含檔案路徑、Prompt 或憑證。

Exit code：`0` 表示全部已恢復到 **TODO 待執行或沒有 Blocked**（不是 LLM 成功）；`1` 仍在冷卻或追蹤；`2` 存在需要人工處理的問題。

## 管理員排查

使用 `python -m scripts.inspect_queue_recovery_state --item-dir ...` 進行唯讀狀態診斷。主要代碼：

- `RECOVERY_ITEM_BLOCKED`：保留原始資料，仍未具備安全自動解除的完整證據。
- `RECOVERY_OPERATOR_ACTION_REQUIRED`：有限次復查仍無法處理，待人工審查。
- `RECOVERY_PENDING`：已由外部安全轉移至 TODO；只是可重新排程，不代表 LLM、Success 或 SQL/ES 寫回成功。

請勿直接批次刪除 Queue、Success 或 marker 來「解鎖」。涉及重複工作身分、外部 sink 寫回與高風險完整重建，需要獨立核實來源、generation 和 sink acknowledgment。

**驗證限制**：GitHub Hosted CI 的假資料檔案測試不等於離線環境、真實 Windows NTFS/SMB、正在執行中的舊 LLM worker 或 SQL/ES readback 驗收；後者仍依 Issue #266 驗證。
