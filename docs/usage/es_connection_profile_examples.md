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

## 內網舊連線 Python 的啟動診斷（唯讀提醒）

部署新程式時，即使內網舊連線 `.py` 尚未整理，若其中有 `rerun`
且與當前 YAML 合併，就會在**啟動的 rerun 摘要**顯示：

- `[ES_RERUN_LEGACY_PY]`：連線 Python 含舊的 `rerun`；顯示 YAML
  指定的 `es_config_file` 檔名（實際設定可能由 `private/` 同名檔載入）。
- `[ES_RERUN_PY_ONLY]`：此 YAML 完全沒有 `rerun`，此次從 Python
  沿用所有重跑設定。
- `[ES_RERUN_PY_INHERITED]`：YAML 只設定部分 key，其他 key 仍從
  Python 繼承；列出繼承的鍵名及可能引發重跑的項目。
- `[ES_RERUN_PY_SHADOWED]`：此任務 YAML 已逐鍵覆寫 Python 舊
  `rerun`（本次沒有繼承），但提醒日後整理共用檔。

常見的意外重跑來源包含 `force_since`、`pipeline_hash`、
`force_if_missing_meta`、`required_output_checks` 與 `stale_after_days`。
警告不輸出私人連線帳密、不列印任意來源設定值，不呼叫 ES、也不修改
任何 `rerun`、YAML、私人 `.py` 或已存資料。只在有舊 Python
`rerun` 時顯示；只從 YAML 取得政策則不產生此類警告。

**後續修正方式：**先把每份任務需要的 `rerun` 放到自己的 YAML，
確認生效的來源／覆寫與繼承鍵，再從共用私人連線 `.py` 移除
整個 `rerun = {...}`。在完成前，**舊設定仍照原本方式生效**，
不要誤以為警告代表自動停用重跑。

### 啟動訊息直接說明設定分工

若連線 Python 留有舊 `rerun`，警告會同時印出新設計原則：
`config_es` Python 只管理 ES 主機、認證、TLS、索引及基本 I/O；
**每份任務 YAML 自己管理 `rerun`、重跑時間窗、版本及輸出品質檢查**。
同一連線檔被多份 YAML 共用時，這樣可避免跨任務繼承重跑政策。
訊息也會附本文件路徑，方便在離線內網部署時查看。

此為**提醒與遷移指引**，只在偵測到舊 Python `rerun` 時印出；
不需要更新私人 `.py` 才能看到警告，但直到手動遷移前，
舊重跑政策仍然生效。純 YAML 設定不額外顯示這個警告。

## 對齊 SRAF Event-first 的 ES 任務 YAML（2026-11-11）

這次專案內直接使用 `InfoExtraction-MultiDim-SQLFriendly-to json format`
的 **10 份 ES mode YAML** 都在各自的頂層定義以下政策：

```yaml
rerun:
  enable: true
  pipeline_hash: null
  force_since: null
  force_if_missing_meta: false
  fallback_date_field: update_time_ai
  required_output_checks:
    - path: multidim_event_json
      validator: multidim_event_time
      min_valid_count: 1
      relative_to_output: false
```

包含一般 ES 模式（news、fishing、mil、nav intel、satmeta、srp、
single-stage original、legacy es_merge）及兩份 ES multistage。
`pipeline_hash: null`、`force_since: null` 是**刻意明寫**，
用來覆寫內網私人連線 Python 尚未刪除的舊強制重跑值；省略這兩個
key 會被原本 Python+YAML 的淺層合併重新繼承。原本三份 YAML 中
的 `v3.2.2-es-multistage-rerun-test` 已取消啟用，以避免單純啟動
就按版本強制重跑。

若將來要重新處理舊資料，應在特定任務 YAML **刻意**把
`pipeline_hash` 或 `force_since` 改為有效值；不需要在
`private/*.py` 中設定。其他私人 Python `rerun` key 若未在 YAML
指定，仍可能被繼承；啟動的 `ES_RERUN_LEGACY_PY` 提示能協助盤點。

此設定只處理**日期結構品質**：既有輸出缺失、格式不合法時仍可能
進入 pending；Event 明確 unknown 也可通過，不能據此斷言原始
新聞沒有日期。跨重啟最多修復幾次仍由 Issue #313 追蹤，
**不是**這次 YAML 變更的內容。本次沒有修改私人設定或接觸 ES 資料。
