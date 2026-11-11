# Elasticsearch Python 範例設定整併與既有任務相容指南

## 原因與範圍

舊版 `czjLLM/config_es/akconfig_es_*.py.example` 共有七份，內容高度重複。
為避免修改日期驗證規則時七份範例逐漸分歧，公開範例統一保留
`czjLLM/config_es/connection.py.example` 一份。這是 **公開範本的整理**，
不是遷移／刪除使用者的私人 `akconfig_es_*.py`，也不調整索引、SQL／ES
寫入，或任一任務 YAML 的 `es_config_file` 指向。

既有任務 YAML 的 `es_config_file` 仍指定不同的 `.py` basename。
程式目前能將該路徑解析為同名
`czjLLM/config_es/private/<basename>.py`，不需要 public `.py.example` 存在。

## 各索引／既有私人檔名對照

以下是 **整理前公開範例** 的 `es_index` 與政策差異；工作站實際
`private/*.py` 的設定必須自行確認，不能把下表視為當前有效連線。

| 任務用私人設定檔名（保留） | 舊公開範例索引 | 舊範例中 `force_since` | 舊範例日期檢查 |
| --- | --- | --- | --- |
| `akconfig_es_test.py` | `news_test` | 啟用，固定日期 | 有 |
| `akconfig_es_test_133.py` | `srp_test` | 啟用，固定日期 | 有 |
| `akconfig_es_test_srp_133.py` | `srp_test` | 註解停用 | 有 |
| `akconfig_es_fishing.py` | `fishing_test` | 啟用，固定日期 | 有 |
| `akconfig_es_test_satmeta_133.py` | `satmeta` | 註解停用 | 有 |
| `akconfig_es_test_mil.py` | `mil_reports-01` | 啟用，固定日期 | 無 |
| `akconfig_es_test_nav_intel_sentences_133.py` | `nav_intel_sentences_synthetic_v1` | 啟用，固定日期 | 無 |

部分舊範例另有 CA／TLS 設定差異（例如軍事範例未明列 CA 相關欄位）。
新的唯一範例統一採 **TLS 主機名驗證開啟、CA 由操作員指定** 的安全預設，
不照搬舊版的 `es_ssl_assert_hostname=False`。

## 新增任務／建立新的私人設定

1. 複製 `czjLLM/config_es/connection.py.example` 為
   `czjLLM/config_es/private/<任務 YAML 中 es_config_file 的檔名>.py`。
   請先確認目標檔案 **不存在**，不要覆寫現有私人設定。
2. 私人檔的 `es_index` 選擇正確索引；透過本機環境變數設定 ES 主機及
   使用者／密碼，並配置符合實際 HTTPS 位址的憑證。
3. 核對 `id_col`、`input_col`、`output_col`、`mapping_file`
   與 `pending_filters`；新範例預設 `es_apply_mapping=False`。
4. 核對主 YAML 與私有設定合併後的 **有效** `rerun`：
   主 YAML 同名 key 會覆蓋私人 Python 設定值；未設定的 key 仍可繼承。
   `rerun.enable=False` 是範例的安全預設，不是現行所有任務的關閉指令。
5. 嚴格限制測試範圍並先做唯讀 pending／日期稽核，確認不會造成
   `news_test` 等歷史資料大量重新抽取後再啟用重跑。

舊版公開範例的 `pipeline_hash="v3.2.1"`、
`force_since="2025-11-01T00:00:00Z"` 不再被當成新任務預設值。
這些值可能使已有成功輸出的資料再次進入 pending。

### 舊工作站需要修改嗎？

**不需要。** 本變更不會刪除或覆寫
`config_es/private/*.py`；若現有任務可運作，原本的私人配置可維持。
若工作站仍使用未納入 Git 的
`czjLLM/config_es/akconfig_es_*.py` 原地設定，也不會因為移除
`.py.example` 而被刪除。之後整理實際連線設定須獨立核實。

## 日期驗證政策與安全邊界

新公開範例保留非強制啟用的 `multidim_event_time` 欄位檢查，
核心 Event 有合法日期，或宣告合法的日期未知，都不必強迫產生
`Event_Timeline` 日期。日期原文語意忠實性仍需另行稽核。
`pipeline_hash`、`force_since`、`force_if_missing_meta` 等
重跑條件不因本次範例整併而自動解除。

品質檢查失敗的跨重啟重試次數上限由 Issue #313 另行追蹤，
本次沒有新增 retry 計數，也沒有寫入 ES／呼叫 LLM。
