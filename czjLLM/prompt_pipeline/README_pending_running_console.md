# Pending Running Console README

`pending_running_console.json` 是 pending 機制的跨程序短期中控檔，用來讓多個主程序在「真正切片與派工前」互相比對某個 target + pk/file 是否已經被其他程序標記為 running。

## 責任邊界

- 中控臺只負責短期協調與排序：把目前 running 的 row/file 延後，優先處理非 running 項目。
- 中控臺不負責判斷資料是否永久完成，也不是長期歷史資料庫。
- 真正的完成判斷仍以 SQL/ES/table/TXT 輸出目標與 pending recheck 為準。
- 即使某筆資料被中控臺判定為 running，也只是本輪先延後；非 running 項目掃完後仍可能回頭處理 deferred running 項目。

## 檔案與保留策略

預設檔案：

```text
{ctx.PGMSubDir}/logs/pending_running_console.json
{ctx.PGMSubDir}/logs/pending_running_console_adjustments.log
```

`pending_running_console.json` 主要包含：

- `running`：目前仍在處理中的 target + pk/file。
- `last_finished`：最近完成或釋放的短期觀察紀錄，預設只保留 1 小時，避免大量批次執行後無限制累積。

`pending_running_console_adjustments.log` 是 JSONL 歷史觀察 log，預設容量上限 30 MB；超過上限時會從最舊資料開始裁掉，保留約後半段較新的紀錄。

## 重要設定

- `pending_running_console_enabled`：是否啟用中控臺，預設 `True`。
- `pending_running_console_path`：自訂 JSON 中控檔路徑。
- `pending_running_console_ttl_seconds`：running 狀態 TTL，預設 24 小時。
- `pending_running_console_finished_retention_seconds`：`last_finished` 保留秒數，預設 1 小時。
- `pending_running_console_log_path`：自訂調整 log 路徑。
- `pending_running_console_log_max_bytes`：調整 log 容量上限，預設 30 MB。

## 損毀恢復

如果 `pending_running_console.json` 在執行中損毀或被截斷，下一次讀取失敗時會重建為空中控臺。這代表 running 比對可能在短時間內失效，造成不同程序短暫更容易撞到同一筆資料；但後續程序重新 `mark_running` 後，中控臺會恢復作用。是否真的派工仍會再由 pending recheck 做最後確認。

更多流程細節請參考 `czjLLM/docs/usage/pending_running_console_and_recheck.md`。
