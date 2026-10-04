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
- `pending_running_console_finished_retention_seconds`：`last_finished` 最近完成/釋放紀錄保留秒數，預設 1 小時；設為 `0` 代表下一次讀寫中控臺時立即清掉舊完成紀錄。

中控臺使用檔鎖保護讀寫，主要記錄：

- `running`：目前被標記為 running 的 target + pk/file；這是跨程序排序與派工前 running 比對的主要依據。
- `last_finished`：最近釋放的項目與釋放狀態，只供短期觀察與除錯，不參與是否派工的核心判斷；預設只保留 1 小時，避免幾萬筆長時間執行後 JSON 無限制膨脹。

因此，`pending_running_console.json` 不是長期歷史資料庫。它是短期、可重建的跨程序中控檔：真正的「是否已完成」仍以 SQL/ES/table/TXT 輸出目標與 pending recheck 為準。

## 中控臺調整 log

為了觀察中控臺是否真的降低重複計算，系統會另外寫 JSONL 調整 log。

預設位置：

```text
{ctx.PGMSubDir}/logs/pending_running_console_adjustments.log
```

可用 ctx 屬性調整：

- `pending_running_console_log_path`：自訂調整 log 路徑。
- `pending_running_console_log_max_bytes`：調整 log 最大大小，預設 30 MB；超過上限時從最舊內容開始裁掉，保留約後半段較新的 JSONL。

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

## 故障、損毀與 stale 狀態

如果主程序崩潰，可能留下 running 狀態。中控臺會透過 TTL 與 dead pid probe 清除 stale running record。若系統中某些工作時間可能超過預設 24 小時，應調大：

```python
ctx.pending_running_console_ttl_seconds = 48 * 60 * 60
```

如果 `pending_running_console.json` 在執行中損毀或被截斷，下一次讀取失敗時會以空的 `{version, running}` 結構重建。影響是損毀到重建這段短時間內，跨程序 running 比對可能暫時失效，其他程序可能短暫無法避開同一 row/file；但後續 producer 重新 `mark_running` 後，中控臺會恢復作用。是否真的要派工仍會再經 pending recheck 確認。

也可以在排查時直接檢查：

```text
logs/pending_running_console.json
logs/pending_running_console_adjustments.log
```

## 建議觀察方式

1. 看 `pending_running_console_adjustments.log` 中 `initial_reorder`、`defer_running` 是否出現。
2. 對照 `pending_recheck_skips.log`：若中控臺有效，重複派工應下降；若仍有大量 pending skip，代表多程序仍常讀到相同 pending 清單，可以調整 block shuffle 或排程間隔。
3. 檢查 `pending_running_console.json` 是否有長期不釋放的 running 項目；若有，確認是否為超長任務或主程序異常中斷。

## L1：持久化結果語意新鮮度與可觀測性

SQL/ES 的目標 row/document 仍是唯一的跨執行 reuse authority；pending-running console 只協調「目前正在執行」，D1 checkpoint 只恢復 round，stage snapshots 只屬於當次執行。L1 沒有 member-result file cache，K2 未持久化的 nested output 下次仍會重算。

`source_version` 回答來源 member 是否改變；`execution_fingerprint` 回答 prompt、task、model semantic config、pipeline/ReductionStage/nested reducer 等處理語意是否改變。兩者互不替代：任何一者依其 policy 改變都應重算，兩者均未變才可安全 reuse。

SQL 以明確的 `semantic_freshness.execution_fingerprint` 與 `semantic_freshness.processing_identity_column` opt in。未設定 expected fingerprint 時，維持所有 output columns 非空即 complete 的舊行為；啟用後，output 非空但 identity 缺少或不相等皆 pending。result 與 identity 由同一 writeback transaction/commit 寫入，避免新 identity 配舊 payload。identity column 必須在設定中明確命名；strict mode 會由既有 schema preparation 建立該明確宣告的文字欄位。

ES 延伸既有 `rerun` policy 的 `execution_fingerprint`，寫入既有 output meta；此條件與 `model_tag`、`pipeline_hash`、required-output、`stale_after_days`、`force_since` 累加，matching fingerprint 不會蓋過其他 stale policy。metadata 仍經現有 sanitization，不保存 credentials 或 endpoint。

Canonical structured stream 預設為：

```text
{ctx.PGMSubDir}/logs/pending_recheck_events.jsonl
```

可用 `pending_recheck_event_log_path` 與 `pending_recheck_event_log_max_bytes` 覆寫；預設上限 30 MB，超限保留約後半段完整 JSONL records。fingerprint 只顯示 12 字元 prefix（比較仍使用全文），不記 raw input、prompt、LLM response、credential、connection string 或 URL。`pending_recheck_skips.log` 繼續產生，作為 legacy narrow compatibility log。

穩定 reason codes 包含 `fresh_completed`、`missing_output`、`row_missing`、`missing_processing_identity`、`execution_fingerprint_mismatch`、`stale_by_policy`、`required_output_invalid`、`recheck_error_fail_open`，ES policy 可保留更具體的 model/pipeline/time reason。正常 missing-output 預設只計數；fresh skip、semantic stale、invalid output 與 fail-open error 一定寫 structured event。

Stats 保留 `checked/pending/already_completed/errors`，並新增 `reasons`、`skip_rate`、`recheck_error_rate`、`semantic_stale_count`；dispatch/finalize/completion scope 分開。GUI 透過 multiprocessing event queue 接收 cumulative snapshot，預設每 100 checks 更新並在 final summary 強制更新；`Recheck Errors` 會直接出現在 compact section/log，不由 producer thread 操作 Tk widget。

## L1 corrective：automatic semantic identity

`execution_fingerprint: auto` is the normal Reduction Engine integration. After effective task/stage/model/reduction settings are available and before destination pending discovery, production constructs the effective existing `TaskExecutable` or `StagePipelineExecutable` (or uses an explicitly supplied K1/K2 executable), wraps row-level reduction/combine semantics, and calls `executable_semantic_fingerprint()`. The full result is bound once to the runtime context, source adapter policy, and writeback sink. A literal value remains an advanced externally managed override.

For SQL, an explicitly configured `processing_identity_column` is schema-owned metadata: strict mode creates it as text alongside output columns. It must not collide case-insensitively with the primary key, input, outputs, writeback outputs, or expanded JSON destinations. Output and identity remain one committed write.

For ES, configured `model_tag`, `pipeline_hash`, and `execution_fingerprint` make missing corresponding metadata stale. Query-side selection, bulk checks, dispatch recheck, and completion recheck therefore use equivalent criteria. Decisions expose stable specific reasons such as `missing_meta`, `model_tag_mismatch`, `pipeline_hash_mismatch`, `missing_processing_identity`, `execution_fingerprint_mismatch`, `stale_after_days`, and `force_since`.

The Windows GUI has a fixed **Recheck Status** section; cumulative queue snapshots replace its displayed value without adding periodic text-log lines. Nonzero errors use warning coloring and log only the transition into an error state. Candidate progress remains separate from the actual count returned by the producer and shown as `producer 實際送出列數`.

PR #193 head `cb12323d0a98ed6bf3eae28182758db24e72f0df`, CI #441 / `36973654548`, job `110732742876`, collected and passed 21/21 offline E2E cases. This is pre-corrective green evidence only: review subsequently found automatic fingerprint wiring, SQL identity collision/schema, persistent GUI status, dispatch-count reporting, and ES metadata-policy consistency gaps. PR L1 and PR L remain pending until a fresh corrective hosted gate passes.

## L1 final corrective：ES Python freshness postfilter 與安全 job identifier

當 single-index ES 啟用 `required_output_checks`（包含 nested/list traversal、date format、`min_valid_count` 等只能由既有 Python validator 精確表達的規則）時，初始查詢會保留 input/pending filters，但不再用 missing-output/rerun `should` 縮窄候選；scan 後由 `check_source_pending()` 作 authoritative postfilter。這可能掃描較多文件，但保證 Python 判定 pending 的文件不會在 discovery 被漏掉。沒有 Python-only validation 規則的普通工作仍使用既有 optimized `missing output OR rerun clause` query。Dual-index 原本即掃 source 並透過 target bulk freshness Python contract 判斷，維持不變。`pending_policy_no_eventids.py` 保持相同 mode 判定與 source-field contract。

Discovery invariant 是：Python freshness 判為 pending 的 unchanged document 必須出現在初始 candidate set；optimized query 可以是 safe superset，因為 dispatch recheck 會跳過 false positive，但不得有 false negative。

Canonical event 與 legacy skip log 的 `task_json` 現在只取明確 config/job path identifier 的 basename，或 bounded simple `pipeline_name`；structured/list/object values、control characters 與完整 directory path 不會輸出。它不再 fallback 到 `ctx.task` 或 prompt content；找不到安全 identifier 時使用 `unknown`。Decision diagnostic allowlist 未擴大。

PR #193 pre-final-corrective head `874dbc865c46a02b5ba76caebbac05b213f94c70`, CI #442 / `37080278738`, offline job `111079056066` collected 21 and passed 21/21. This remains pre-final-corrective green evidence: review found single-index required-output false negatives and raw `ctx.task` diagnostic leakage risk. PR L1 and PR L remain pending a fresh final-corrective hosted gate.
