# 多維事件 Output Profile 歷史輸出唯讀稽核（Issue #294，Phase A）

本工具僅在本機對**已輸出的 NDJSON** 重新執行目前的 `normalize_multidim_event_payload` 結構檢查，將結果統計為固定類別。它不修改 `multidim_event` 正規化、ES pending／rerun、Mapping、提示詞或任何寫回流程。

## 使用方式

先由操作員自行以受控方式匯出已存在的 ES `_source` 成 NDJSON；每行一個 JSON object，包含 `{"_source":{"multidim_event_json":[...]}}` 或 `{"multidim_event_json":[...]}`。**本工具不負責連線或匯出 ES**。來源匯出可能包含敏感新聞正文、文件 ID 與模型內容，必須保存在受控本機目錄。

Windows：

```bat
python scripts/audit_multidim_profile_offline.py --input-ndjson "D:\\private\\stored_es_source.jsonl" --human
```

Linux：

```bash
python scripts/audit_multidim_profile_offline.py --input-ndjson "/private/stored_es_source.jsonl"
```

預設 stdout 只輸出固定欄位 JSON 統計；`--human` 輸出固定繁體中文名稱與數量。回傳 0 表示已觀察到可解析的非空輸入，**並非來源真實、Profile 語意正確、實際 ES 讀回驗收或允許重跑**。回傳 2／`UNAVAILABLE` 是不可驗證，無部分計數。

## 統計類別

| 代碼 | 僅可推論 |
|---|---|
| `SOURCE_UNVERIFIED` | NDJSON 物件或 `_source` 封套不能確認 |
| `OUTPUT_ABSENT` | `multidim_event_json` 缺失、null 或空陣列 |
| `PROFILE_REJECTED` | **目前版本** Output Profile 格式／參照驗證拒絕（不顯示原始錯誤） |
| `PROFILE_ACCEPTED_NO_EVENTS` | Profile 可接受的構造，但至少一個 article block 沒有 Event；不能當成有效事件證據 |
| `PROFILE_ACCEPTED_EVENT_DATE_EMPTY_TIMELINE` | Profile 接受、至少一筆 Event 有 ISO 日期，且**每個原始 article block 明列 `Event_Timeline: []`** |
| `PROFILE_ACCEPTED_EVENT_AND_TIMELINE_DATES` | Profile 接受，Event 與 Timeline 各有已格式驗證日期 |
| `PROFILE_ACCEPTED_TIMELINE_DATE_ONLY` | Profile 接受，Timeline 有已驗證日期、Event 無 |
| `PROFILE_ACCEPTED_EVENT_DATE_OTHER` | Profile 接受，Event 有日期但 Timeline 非全面明示為空，且沒有其他已驗證 Timeline 日期 |
| `PROFILE_ACCEPTED_DATE_UNKNOWN` | Profile 接受，但沒有經格式驗證的 Event／Timeline 日期；不代表原文章無日期 |

所有類別互斥；同一文件有多個 article block 時，**任一 block 被 Profile 拒絕，整份文件即屬 `PROFILE_REJECTED`**。Profile 所允許的欄位、`event_ids` 參照、日期精度由既有 Production Profile 決定；此工具不自行創建另一套 schema。原始資料與正規化結果不被修改，不展示例外訊息、文件 ID、日期、路徑、正文、LLM 內容或來源端點。

## 與既有日期稽核的區別

現有 `scripts/audit_multidim_event_time.py` 僅檢查 time fields；即使它顯示 `EVENT_DATE_EMPTY_TIMELINE`，仍可能有 Evidence 的 `event_ids` 指向不存在的 Event。新工具會以**目前完整 Profile** 拒絕此結構。兩份報表提供互補的數量，不是互相替代的真實性或 pending 判定。

輸入與原日期稽核共用既有私有檔讀取器：上限 16 MiB、20,000 行、單行 512 KiB，拒絕符號連結、損壞 JSON、截斷末行或讀取時改變檔案身分；不可保證惡意並行修改者不可繞過檔案快照。請在受控、停止寫入後的私有匯出檔執行。

**未驗證事項：** 來源文章日期忠實性、LLM 是否漏抽／幻覺、Output Profile 版本與歷史寫入當時版本是否一致、現行 ES rerun 及 fingerprint、索引 Mapping、實際 ES sink ACK 與 SQL/ES 端來源原子性。Profile 合規也不代表完成全部事件或通過 SRAF Evidence 檢索；反之，Profile 拒絕舊資料不能視為已授權覆寫或大規模重跑。

正式改動任何 ES pending／重新抽取前，請分別稽核工作站 YAML 與私人 `.py` 的有效 rerun、確認既有資料受影響筆數、代表性來源原文與讀回證據，取得操作員明確授權。此 PR 只新增離線觀測與測試。
