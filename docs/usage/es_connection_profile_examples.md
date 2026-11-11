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
4. 每份**任務 YAML 自己負責 `rerun`**。共用的連線 Python 不應設定 `rerun`。
   舊程式仍允許私人 Python 與 YAML 的 `rerun` 逐 key 合併，
   所以需要人工移除既有私人 `.py` 中的整段 `rerun = {...}`。
   只在 YAML 寫 `enable: false` 並不等於已清除所有可能繼承的條件。
5. 嚴格限制測試範圍並先做唯讀 pending／日期稽核，確認不會造成
   `news_test` 等歷史資料大量重新抽取後再啟用重跑。

舊版公開範例的 `pipeline_hash="v3.2.1"`、
`force_since="2025-11-01T00:00:00Z"` 不再被當成新任務預設值。
這些值可能使已有成功輸出的資料再次進入 pending。

### 舊工作站需要修改嗎？

本 PR **不會刪除或覆寫** `config_es/private/*.py` 或未追蹤的
`config_es/akconfig_es_*.py`。為改採 YAML-only 重跑政策，操作員需
手動刪除其私人連線 `.py` 中整段 `rerun = {...}`，並核對各任務 YAML。
請注意：`es_config.yaml`、`es_config_mil.yaml`、`es_config_srp.yaml`
等目前並未定義 `rerun`；舊執行結果可能仰賴私人 `.py` 的舊政策。
遷移後要刻意確認是否仍需在相關 YAML 補上這些規則，避免靜默改變任務語意。

## 日期驗證政策與安全邊界

新公開的 ES Python 連線範例**完全不包含 `rerun`**。
多維度事件日期檢查需放入具體任務 YAML，使用
`validator: multidim_event_time`：Event 合法日期或明示未知皆可通過，
Timeline 可為空。日期原文語意忠實性仍需另外稽核。
`pipeline_hash`、`force_since`、`force_if_missing_meta` 等
重跑條件不因本次範例整併而自動解除。

品質檢查失敗的跨重啟重試次數上限由 Issue #313 另行追蹤，
本次沒有新增 retry 計數，也沒有寫入 ES／呼叫 LLM。

## YAML-only 重跑政策（建議）

以下只適合多維事件任務，且須先部署含 `multidim_event_time`
驗證器的版本。不要直接把舊版測試用 hash 搬入正式排程：

```yaml
rerun:
  enable: true
  force_if_missing_meta: false
  required_output_checks:
    - path: multidim_event_json
      validator: multidim_event_time
      min_valid_count: 1
      relative_to_output: false
```

`pipeline_hash`、`force_since`、`model_tag`、`stale_after_days`、
`execution_fingerprint` 等須由**該任務 YAML 明確選擇**，不能由連線
設定檔共享。如果 YAML 完全沒有 `rerun`，從 Python 移除後就不會有
過去 Python 的自訂重跑政策；要先確認這是預期行為。

### 向後相容注意事項

現有 `czjLLM/es_mode/config/rerun_logging.py` 仍採舊式
Python + YAML `rerun` 淺層合併。此次先把**公開範例改為 YAML-only**，
不直接禁止舊私人設定，以免在尚未盤點生產設定前讓既有任務失效。
操作員完成私人設定遷移後，所有新政策才真正由 YAML 決定。

啟動時若程式偵測到私人連線 Python 仍含舊 `rerun`，會顯示明確警告。
但為避免突然改掉舊排程，本 PR 不會自動忽略或停用這些值；它仍保留
原來的合併語意，直到操作員完成私人設定遷移。
