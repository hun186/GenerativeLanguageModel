# 舊版單階段 YAML 與新版多階段 YAML 寫法／流程指南

本文說明 czjLLM 在 ES、SQL / SQLite、Excel / CSV（table）與 TXT 模式下，如何判斷「舊版單階段」與「新版多階段」任務，以及兩種 YAML 的寫法注意事項與執行流程差異。

## 快速結論

- **舊版單階段 YAML**：只宣告 `task`、`input_col`、`output_col` 等欄位，沒有 `stage_cfg.stages` / `stages` / `task_config.stages`，也沒有 `source: stage` 的 writeback rules。
- **新版多階段 YAML**：明確宣告 `stage_cfg.stages`、頂層 `stages`、或 `task_config.stages`；若要讓寫回指定某個 stage 的輸出，需使用 `es_writeback_rules` 或 `sql_writeback_rules` 並設定 `source: stage` 與 `stage`。
- **不要為了表示單階段而放空的 `stage_cfg: {}`**。若只是舊版單階段，請完全省略 `stage_cfg` / `stages`。
- ES entry 可能會在 runtime 補上空的或相容用 `stage_cfg` metadata；系統現在只會在 `stage_cfg` 真正宣告 runnable flow 時才視為多階段。
- 舊版單階段依然走 legacy consumer：切片產生 TODO → consumer 呼叫 LLM → combined output → row merger/sink 寫回 `output_col`。
- 新版多階段走 stage-managed path：切片後由 scheduler / `process_prompt_and_merge_multistage()` 依 stage 順序同步執行 → 輸出 `_stage_merges/manifest.json` → row merger 依 writeback rules 取 stage 或 combined 輸出寫回。

## 判斷規則

系統內部使用兩個層次判斷：

1. `ctx.stages` / `task_config.stages` 是否存在且為非空 list。
2. ES `stage_cfg` 是否真的宣告 runnable flow。

下列情況**不算**多階段：

```yaml
task: InfoExtraction-MultiDim-SQLFriendly-to json format
output_col: multidim_event_json
```

```yaml
# 不建議特別寫；若 runtime 出現這種相容 metadata，也不應停用 legacy consumer。
stage_cfg: {}
```

```yaml
# compatibility metadata，不代表真的有可執行 stage flow。
stage_cfg:
  name: single_stage
  enabled: false
```

下列情況**算**多階段 / stage-managed：

```yaml
stage_cfg:
  stages:
    - name: extract
      task: "@taskSetting:InfoExtraction-MultiDim-SQLFriendly-to json format"
      input_from: original
      output_col: multidim_event_json
```

```yaml
task_config:
  stages:
    - name: extract
      task: DemoTask
```

```yaml
stage_cfg:
  enabled: true
  stages:
    - name: extract
      task: DemoTask
```

## 舊版單階段 YAML 寫法

### ES 單階段範例

```yaml
mode: es
channel: unspecified_channel
model_spec: gpt-oss:120b-ctx-32k-premises-MXFP4
es_config_file: czjLLM/config_es/akconfig_es_test_srp_133.py

input_col: rawInfo.content
primary_key: _id
output_col: multidim_event_json
task: InfoExtraction-MultiDim-SQLFriendly-to json format
record_update_time: true

merge_slices: true
merge_log_changes: true
merge_max_log: 10
merge_log_to_file: true
merge_log_file: merge_dict_slices_audited.log

# 舊版單階段請不要加：
# stage_cfg:
# es_writeback_rules:
```

#### ES 單階段流程

1. ES adapter 找出 pending 文件。
2. scheduler 將 `rawInfo.content` 寫成暫存 txt 並切片，產生 prompt TODO。
3. `llm_stream_consumer()` 批次取 TODO 呼叫 LLM。
4. LLM 回覆進入 Success 後，combined output 被產生。
5. row merger 讀 combined output，必要時依 `merge_slices` 合併 list of dict slices。
6. `ESSink.write_main()` 寫回 `output_col`；若 `record_update_time: true`，也寫入 `update_time_ai` / meta 相關欄位。

### SQL / SQLite 單階段範例

SQL Server 與 SQLite 共用 SQL mode；SQLite 通常由 `server` 或 config 指向 `.sqlite` / `.db` 檔案。

```yaml
mode: sql
input_col: Content
output_col: LLM_result
primary_key: id
task: SomeTask-to json format
record_update_time: true

# 舊版單階段請不要加：
# stages:
# task_config:
# sql_writeback_rules:
```

#### SQL / SQLite 單階段流程

1. SQL adapter 依 `output_col` 是否缺值找 pending rows。
2. scheduler 將每列文字存成暫存 txt 並切片。
3. consumer 呼叫 LLM 並產出 combined output。
4. row merger 將 combined output 寫回 `output_col`。
5. 若啟用 flatten，會再依 flatten 設定展開 JSON 到子表或相關欄位。

### Excel / CSV（table）單階段範例

```yaml
mode: table
input_col: Text
output_col: LLM_result
primary_key: row_id
task: SomeTask-to json format
record_update_time: true

# 舊版單階段請不要加：
# stages:
# sql_writeback_rules:
```

Table mode 與 SQL mode 共用 stream scheduler / row merger 的大部分流程，只是 sink 會寫回 dataframe / Excel / CSV 輸出。

### TXT 單階段範例

```yaml
mode: txt
task: Summary-toTWZH
model_spec: gpt-oss:120b-ctx-32k-premises-MXFP4
llm_source_dir: ./LLMSourcePool/txt_demo
llm_source_backup_dir: ./LLMSourcePool_origin_backup/txt_demo

# 舊版單階段請不要加：
# stages:
# task_config:
```

TXT 單階段不走資料庫 row writeback；重點是 prompt TODO → LLM → combined 檔案輸出與來源檔備份。

## 新版多階段 YAML 寫法

### ES 多階段範例

```yaml
mode: es
channel: unspecified_channel
model_spec: gpt-oss:120b-ctx-32k-premises-MXFP4
es_config_file: czjLLM/config_es/akconfig_es_fishing.py

input_col: rawInfo.content
primary_key: _id
output_col: multidim_event_json
output_profile: multidim_event
record_update_time: true

merge_slices: true
merge_conflict_policy: prefer_left
merge_dedup_lists: true

stage_cfg:
  name: es_json_multistage_langroute
  version: v0.2
  default_route: fallback
  stages:
    - name: extract
      task: "@taskSetting:InfoExtraction-MultiDim-SQLFriendly-to json format"
      input_from: original
      input_col: rawInfo.content
      output_col: multidim_event_json
      output_profile: multidim_event
      persist_output: final
      write_output: true
      max_attempts: 2
  stage_outputs:
    keep_intermediate: false
    meta_field: multidim_event_json_meta
    final_output_col: multidim_event_json

es_writeback_rules:
  - output_col: multidim_event_json
    source: stage
    stage: extract
    index: fishing_test
    output_type: nested
    output_profile: multidim_event
    meta_field: multidim_event_json_meta
    normalize_payload_dates: true
    meta_base:
      task: InfoExtraction-MultiDim-SQLFriendly-to json format
      stage: extract
```

### SQL / SQLite 多階段範例

```yaml
mode: sql
input_col: Content
output_col: File_result
primary_key: id
task: InitialTask
record_update_time: true

stages:
  - name: route
    task: RouteTask
    input_from: original
    output_col: File_route
    persist_output: always
  - name: extract
    task: ExtractTask-to json format
    input_from: original
    output_col: File_result
    persist_output: final

sql_writeback_rules:
  - output_col: File_route
    source: stage
    stage: route
  - output_col: File_result
    source: stage
    stage: extract
```

SQLite 使用同一組 `stages` / `sql_writeback_rules` 語意；差別只在 adapter 與 schema 建立方式。

### TXT 多階段範例

```yaml
mode: txt
model_spec: gpt-oss:120b-ctx-32k-premises-MXFP4
llm_source_dir: ./LLMSourcePool/txt_demo
llm_source_backup_dir: ./LLMSourcePool_origin_backup/txt_demo

task_config:
  stages:
    - name: translate
      task: Translation-toTWZH
      input_from: original
      persist_output: always
    - name: summarize
      task: Summary-toTWZH
      input_from: previous
      persist_output: final
```

## 多階段流程原理

1. **設定載入**
   - ES 會將 `stage_cfg` normalize 後掛到 `ctx.stage_cfg`。
   - SQL / SQLite / table 通常直接使用 `stages` 或 `task_config.stages`。
   - TXT 可使用 `task_config.stages` 或既有 stage 設定格式。

2. **是否 stage-managed**
   - 有明確 stage flow 時，stream scheduler 會在排程階段直接呼叫 `process_prompt_and_merge()`，進一步進入多階段 orchestration。
   - 沒有明確 stage flow 時，保留 legacy consumer path。

3. **stage 執行**
   - 每個 stage 依 `input_from` 決定輸入：`original`、`previous`、指定 stage 名稱或空輸入。
   - 每個 stage 可設定 `max_attempts`、`retry_source_on_route_miss`、`persist_output` 等行為。

4. **stage output 與 manifest**
   - 多階段會在 `_stage_outputs/<stage>/` 保留每個 chunk 的 stage output snapshot。
   - 若該 stage 需要合併輸出，會在 `_stage_merges/<main_name>/` 產生 merged file 與 `manifest.json`。

5. **寫回**
   - 若 writeback rule 設定 `source: stage`，row merger 依 `stage` 名稱從 manifest 找指定 stage 輸出寫回。
   - 若沒有 stage writeback rule，則退回 combined output 寫回主 `output_col`。

## 寫法注意事項

### 舊版單階段注意事項

- 不要加空的 `stage_cfg: {}`、空的 `stages: []` 或空的 `task_config.stages` 來表示「單階段」。單階段請直接省略它們。
- 不要在舊單階段加 `source: stage` 的 writeback rule；否則 row merger 會尋找 stage manifest。
- 如果只需要將所有切片 JSON 合併為一個 dict/list，使用 `merge_slices` 系列設定即可，不需要多階段。
- ES 若使用 nested/object mapping，建議搭配正確的 `output_profile` 或既有 output profile normalization，避免 ES 拒寫 mapping 不相容資料。

### 新版多階段注意事項

- 每個 stage 建議設定穩定的 `name`，因為 writeback rules 會用 `stage` 名稱定位輸出。
- 需要被寫回的 stage 應設定可產生 merged output 的策略，例如 `persist_output: always`，或確認該 stage 是 final output。
- `input_from: previous` 代表接續上一 stage 的輸出；`input_from: original` 代表每個 stage 都看原文。
- ES 多階段若需要寫回特定 index / mapping / meta，請使用 `es_writeback_rules`，不要只依賴頂層 `output_col`。
- SQL / SQLite 多階段若要多欄位寫回，請用 `sql_writeback_rules` 並確認目標欄位 schema 已建立或可自動建立。

## 常見問題

### 為什麼舊單階段不應被當成一個 stage？

`resolve_pipeline_stages(ctx)` 為了相容性，可能會把 plain `ctx.task` 包成一個內部 one-stage representation。但這只是方便共用 stage runtime 的資料結構，不代表 YAML 明確宣告了多階段流程。stream consumer / row merger 需要更嚴格的訊號，否則舊單階段會被錯誤停用 legacy consumer。

### 為什麼空 `stage_cfg` 不能視為多階段？

空 dict 只表示 runtime 或 config loader 有這個欄位，不代表有可執行的 stage、route 或 step。只有 `enabled: true` 或明確宣告 `stages` / `steps` / `routes` / `router` 才能停用 legacy consumer。

### 舊單階段也可以寫 `merge_slices: true` 嗎？

可以。`merge_slices` 是切片結果合併策略，不等於多階段。舊單階段可用它將多個 slice 的 JSON dict/list 合併後再寫回主 `output_col`。

### `merge_slices` 會合併哪些東西？會不會把同一個 JSON list 內的多筆資料合成一筆？

`merge_slices` 只處理「同一筆來源資料因 `InputCutLen` / chunking 被切成多個 prompt slice」後，**不同 slice 成功輸出之間**的合併；它不是用來合併同一個 LLM 回覆 JSON list 裡的多個實體。

行為準則如下：

- 若單一成功 slice 回傳 `[{...}, {...}]`，系統會保留為 list，讓後續主欄位寫回或 JSON flatten 可以保存所有 dict。
- 只有實際存在兩個以上成功 JSON slice 時，才會把多個 slice 的 dict/list 結果送進 `merge_dict_slices_audited()` 做跨 slice 合併。
- `merge_conflict_policy` 只在跨 slice 合併時處理同名 scalar 欄位衝突；預設 `prefer_left` 代表保留較早 slice 的值，`prefer_right` 則保留較晚 slice 的值。
- `merge_dedup_lists` 只在跨 slice 合併時處理 list 欄位去重，不會把 list 裡的多個 dict 實體壓成單一 dict。

例如單任務 YAML：

```yaml
task: Organization Profile Analyzer to json format
merge_slices: true
allowed_output_fields: [route, inputName, formalName, functionalDomain, keyFunctions]
```

若某一個 LLM 成功輸出是：

```json
[
  {"inputName": "海巡署", "formalName": "中華民國行政院海巡署"},
  {"inputName": "警政署", "formalName": "中華民國行政院警政署"}
]
```

合併後仍應是兩筆 list item；它們代表同一個 slice 內抽出的兩個組織實體，不是兩個互相衝突的 slice dict。

### 新版只有一個 stage 也算多階段嗎？

如果 YAML 明確宣告 `stage_cfg.stages` / `stages` / `task_config.stages`，即使只有一個 stage，也會走 stage-managed path。這是預期行為，因為使用者已明確要求 stage runtime 與 stage writeback 語意。
