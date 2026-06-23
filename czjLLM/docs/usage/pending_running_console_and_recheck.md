# Pending Recheck 與 Running Pending 中控臺排程機制

本文件記錄目前避免多主程序重複計算的兩層排程管理機制，避免日後忘記各元件的責任邊界與執行順序。

## 目標

當多個主程序被排程器同時啟動，可能會讀到相同 pending 清單並重複切片、送 LLM、寫回結果。系統用兩層機制降低算力浪費：

1. **Running pending 中控臺**：跨主程序記錄「哪些目標正在 running」，讓 producer 優先處理目前沒有 running 的 row/file。
2. **Pending recheck**：真正派工前再次查目的地（SQL/ES/table 狀態），確認輸出仍未完成；若已完成就不派工。

中控臺負責「調整順序、降低碰撞」，pending recheck 負責「最後確認、避免已完成工作再次被送出」。兩者是互補，不是互斥。

## 適用模式

| 模式 | 中控臺支援 | Pending recheck 支援 | 備註 |
| --- | --- | --- | --- |
| SQL | 是 | 是 | 透過共用 producer 先避開 running row，再用 adapter `is_row_pending` 做最終確認。 |
| ES | 是 | 是 | 透過共用 producer 與 ES adapter 做最終 pending 確認。 |
| Excel / CSV / table | 是 | 視現有 pending 判定能力 | 共用 data-mode producer，因此可使用中控臺排序；是否能做目的地 recheck 取決於 ctx/adapter 是否提供 pending check。 |
| TXT | 是 | 不同於 SQL/ES 的 row-level adapter recheck | TXT mode 以檔案路徑作為中控 key，處理完成或失敗時釋放 running 狀態。 |

## 中控臺狀態檔

預設位置：

```text
{ctx.PGMSubDir}/logs/pending_running_console.json
```

可用 ctx 屬性調整：

- `pending_running_console_enabled`：是否啟用，預設 `True`。
- `pending_running_console_path`：自訂中控臺 JSON 檔路徑。
- `pending_running_console_ttl_seconds`：running 狀態 TTL，預設 24 小時；超過 TTL 的 stale running record 會被清除。

中控臺使用檔鎖保護讀寫，主要記錄：

- `running`：目前被標記為 running 的 target + pk/file。
- `last_finished`：最近釋放的項目與釋放狀態，方便觀察。

## 中控臺調整 log

為了觀察中控臺是否真的降低重複計算，系統會另外寫 JSONL 調整 log。

預設位置：

```text
{ctx.PGMSubDir}/logs/pending_running_console_adjustments.log
```

可用 ctx 屬性調整：

- `pending_running_console_log_path`：自訂調整 log 路徑。
- `pending_running_console_log_max_bytes`：調整 log 最大大小，預設 30 MB；超過時保留後半段。

常見事件：

- `initial_reorder`：初始 pending 清單中發現 running 項目，因此將 running 項目排到非 running 項目之後。
- `defer_running`：data-mode producer 在真正要處理某 row 前再次發現該 pk 正在 running，因此先放入 deferred queue。
- `fallback_revisit_running`：非 running 項目都掃過後，開始回頭處理 deferred running 項目。
- `mark_running_before_dispatch`：data-mode producer 通過 pending recheck 後，準備派工前標記 running。
- `txt_defer_running`：TXT mode 發現檔案正在 running，先延後。
- `txt_fallback_revisit_running`：TXT mode 掃完非 running 檔案後，回頭處理 deferred running 檔案。
- `txt_mark_running_before_dispatch`：TXT mode 處理檔案前標記 running。

每筆 log 會包含 `ts`、`event`、`pid`、`mode`、`task_json`、`target`，若適用也會包含 `pk` 與 deferred 數量等欄位。

## Data-mode producer 執行順序

SQL、ES、Excel、CSV/table 會走共用 producer，其順序如下：

1. 讀取 pending 清單。
2. 依設定做 block shuffle（若啟用）。
3. 呼叫中控臺排序：running row 排在非 running row 後面。
4. 逐列處理前再次查中控臺：
   - 若仍是 running，先放入 deferred queue。
   - 若目前掃到最後一列，且 deferred queue 不空，進入 fallback phase，回頭處理 deferred running rows。
5. 對選定 row 做 pending recheck：
   - 若目的地已完成，記錄 pending skip，釋放中控臺 running 狀態，並跳過派工。
   - 若仍 pending，標記中控臺 running，然後照原流程 `schedule_one_row`。
6. producer drain 後，對已派工 pk 做 finalize：
   - 若 pending check 顯示已完成，標記 completed。
   - 否則釋放為 `released_pending`，避免 stale running 長期卡住。

重點：fallback phase 不是跳過 running 項目，而是「等非 running 都掃過一次，再回頭處理」。

## TXT mode 執行順序

TXT mode 沒有 SQL/ES adapter，因此中控臺以檔案路徑作為 pk：

1. 掃描來源目錄中的 `.txt` 檔案。
2. 呼叫中控臺排序，先處理非 running 檔案。
3. 處理前再次查中控臺：若 running，先 deferred。
4. 非 running 檔案掃完後，回頭處理 deferred running 檔案。
5. 處理檔案前標記 running。
6. 成功處理後標記 completed；若例外，釋放為 `failed_released` 後重新拋出例外。

## 與 pending recheck 的關係

- 中控臺是「協調目前正在跑什麼」：避免多個主程序同時搶同一個 row/file。
- Pending recheck 是「確認目標是否已經完成」：避免已完成資料再次送 LLM。
- 中控臺即使判定 running，也不會永久跳過；只會延後，等其他非 running 項目都掃過後再回頭處理。
- Pending recheck 若判定已完成，才會真的跳過本次派工。

## 故障與 stale 狀態

如果主程序崩潰，可能留下 running 狀態。中控臺會透過 TTL 清除 stale record。若系統中某些工作時間可能超過預設 24 小時，應調大：

```python
ctx.pending_running_console_ttl_seconds = 48 * 60 * 60
```

也可以在排查時直接檢查：

```text
logs/pending_running_console.json
logs/pending_running_console_adjustments.log
```

## 建議觀察方式

1. 看 `pending_running_console_adjustments.log` 中 `initial_reorder`、`defer_running` 是否出現。
2. 對照 `pending_recheck_skips.log`：若中控臺有效，重複派工應下降；若仍有大量 pending skip，代表多程序仍常讀到相同 pending 清單，可以調整 block shuffle 或排程間隔。
3. 檢查 `pending_running_console.json` 是否有長期不釋放的 running 項目；若有，確認是否為超長任務或主程序異常中斷。
