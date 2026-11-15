# ES 品質修復次數上限：離線契約（Issue #313 Phase A）

**此 PR 只有離線、不可變狀態轉移與合成回歸測試。不是跨重啟的持久化重跑限制，也沒有改變現有 ES、Queue、LLM、Scheduler 或資料庫。**

實作：`czjLLM/es_mode/quality_retry_contract.py`。沒有 I/O、沒有生產配置與部署開關。

## 品質重跑政策

- `RetryPolicy(enabled=False, max_failed_repairs=2)`：預設 OFF。首次抽取不扣修復額度；只有「完整修復結果經外部 Output Profile 明確判為不合格」才將 `failed_repairs` 加一。兩次不合格後 `NEEDS_REVIEW`／`QUALITY_RETRY_EXHAUSTED`，不得標為 `fresh_completed`。
- `ACCEPTED_UNKNOWN_DATE` 必須是由有效 Profile 接受的真正未知，不是空日期就當合格。合法 Event 日期與 `Event_Timeline=[]` 亦須遵守 #293 契約。這個模組 **不自行驗證事件日期**，不碰 #312。
- `PROVEN_NO_RESULT` 必須有可信的外部事實能證明沒有完整結果。GPU 忙碌、ES 429、HTTP timeout、主程序崩潰、ES ACK 不明，都不是證明；這些屬於 `UNCERTAIN`，必須人工／可信外部證據釐清再恢復，而非無限派工。
- 每一筆候選以完整 `source_document_id + output_col + verified_pipeline_sha256 + quality_rule_version` 辨別版本。SHA256 字串格式不能證明 Pipeline 真正已驗證，信任綁定必須由未來 adapter 提供；內部資料結構不在 repr 輸出原始來源 ID、fingerprint 或 attempt UUID。
- Claim 與 Finalize 都要求 UUID4 attempt ID 與 `expected_revision`，以離線方式模擬重複觸發保護。**純函式 revision 不是跨程序 CAS 或持久帳本**；離線 ThreadPool test 也不是跨機器原子性證明。
- 任何從持久層重建或直接構造的 `RetryState` 也必須符合**與選擇的 1／2 次政策無關的可達狀態不變條件**：失敗數不超過 2、達 2 只能 `NEEDS_REVIEW`、`NEEDS_REVIEW` 至少有 1 次失敗，未驗證初次狀態不得已有修復／Reset，修復／待檢查必須保留固定品質失敗碼、Reset 世代須具操作 ID。遇到不可能狀態要拒絕，不得把已耗盡狀態讀成成功或進行中。
- 人工 reset 只能從 `NEEDS_REVIEW`，需要外部授權與唯一操作 UUID；純函式中的 `operator_authorized=True` 並不是身分驗證。真正部署需將權限、不可竄改稽核與 ledger Reset 合為原子操作。

## 狀態對照

| 既有狀態 | 確認事件 | 新狀態 | 修復失敗次數 |
|---|---|---|---|
| UNASSESSED | 初次合格／合法 unknown | COMPLETE | 0 |
| UNASSESSED | 初次明確不合格 | READY | 0 |
| READY | 經核准的 claim 提案 | IN_FLIGHT | 不增加 |
| IN_FLIGHT | 完整修復但品質失敗 | READY / NEEDS_REVIEW | 加 1，最多 2 |
| IN_FLIGHT | 完整修復且合格／合法 unknown | COMPLETE | 不增加 |
| IN_FLIGHT | 已證明無完整結果 | READY | 不增加 |
| IN_FLIGHT | 崩潰、結果不確定 | UNCERTAIN | 不增加、禁止自動派工 |
| UNCERTAIN | 已取得可信的完成／無結果證據 | 依品質判定恢復 | 依品質失敗與否 |
| NEEDS_REVIEW | 有稽核的人工核准 Reset（未來） | READY | 歸零、reset generation +1 |

## 正式上線前還缺什麼

1. 讀取並核對實際 Output Profile、私人 `.py`／YAML 有效配置，驗證 source ID、Pipeline 執行版本、品質檢查版本；不能僅憑 SHA 格式聲稱可信。
2. 選擇 sidecar ledger／ES 專用狀態索引並實作跨程序／跨主機原子 claim、finalize、版本 CAS、落盤／斷電重啟及操作審計。因為不合格結果可能無法寫回 ES，不能假設 `multidim_event_json_meta.retry_count` 一定存在。
3. 避免錯把 Pending/Recheck、HTTP retry、429、GPU busy、Worker Crash、ES sink ACK 不明記成完成修復；重啟時不明 claim 必須保留阻擋直到可信 reconciliation，不能悄悄重派。
4. `force_since`、`pipeline_hash`、`execution_fingerprint` 與使用者明確強制重跑必須各有獨立語意與授權，不得偷渡繞過品質額度或破壞既有 force 行為。
5. 先對 `news_test` 作唯讀資料影響統計，驗證 Event 日期、Timeline 為空、unknown、格式錯誤與跨版本的差異；再做可丟棄 ES adapter、雙 Producer、真實 Restart／Crash Recovery 實測。獨立安全審查與 operator ES sink readback 未通過前不得啟用正式重跑。

## 離線驗證

`python -m pytest -q tests/es_mode/test_quality_retry_contract.py`

測試僅使用合成身份、固定 UUID、離線狀態；Hosted Linux 和 Windows Python 3.10／3.11 皆需通過 CI。此階段是可用於未來持久 adapter 的純邏輯契約，不是完整 Issue #313 的完成宣告。
