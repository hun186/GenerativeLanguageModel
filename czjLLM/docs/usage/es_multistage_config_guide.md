# Elasticsearch 多階段任務設定指南

ES 模式現在可比照 SQL/Table 多階段流程，用 YAML 控制任務流路、輸入來源、重試、debug、寫回欄位與 mapping。

## 核心設計

- `stages`：沿用既有多階段語意，支援 `prompt` / `task` / `@taskSetting:<key>` 雙軌來源。
- `input_from`：每階段可選 `original`、`previous`、指定 stage 名稱，或 `none` 不串接來源文字。
- `input_col`：ES 可針對單一 stage 指定不同 dot-path 來源欄位，例如 `rawInfo.subject`。
- `max_attempts`：某階段失敗時可重試數次。
- `debug_print_llm_io` / `debug_print_max_chars`：印出組裝後的 LLM prompt 與回傳內容。
- `es_writeback_rules`：控制各階段輸出要不要寫回、寫到哪個欄位與哪個 index。
- `es_output_mappings` / rule-level `mapping_file`：在寫入前套用 index mapping；若 mapping 未指定，系統會用 `output_type` 建立最小欄位 mapping。

## 範例

完整範例請見：

```bash
python -m czjLLM.czjLLM_TextProcessing --config yaml/es_multistage_langroute_config.yaml
```


## `input_col` 與 stage 額外輸入欄位

ES 的頂層 `input_col` 是用來挑選待處理文件、建立原始切片的主文字來源。多階段 YAML 內的 stage `input_col` 則是「該階段要改用的來源欄位」；程式會把這些 stage dot-path 一併從 ES `_source` 取回，放進 row-scoped `stage_source_inputs`，不會取代頂層 `input_col`。例如 route 階段可讀 `rawInfo.subject`，extract 階段仍讀 `rawInfo.content`。

## 為什麼 ES 不提供 flatten writeback？

SQL/Table 模式需要 flatten 到子表，是因為資料表欄位對巢狀 JSON / list[dict] 的支援有限；ES 原生可以保存 `object` / `nested` 欄位，因此 ES 模式會直接寫入 JSON 結構，不再讀取 `es_flatten_writeback_rules` 或 `sql_flatten_writeback_rules`。若需要查詢友善的結構，請在 `es_writeback_rules.output_type` 設為 `object` 或 `nested`，並用 `mapping_file` 或 `es_output_mappings` 宣告 mapping。

## `es_writeback_rules`

每一條規則可設定：

```yaml
es_writeback_rules:
  - output_col: org_profile_result
    source: stage          # combined | stage
    stage: extract         # source=stage 時指定 stage name
    index: es_results      # 未指定則使用 es_config 的 tgt_index
    output_type: nested    # nested | object | keyword | text | date | long | double
    mapping_file: path/to/mapping.yaml
    apply_mapping: true
    meta_field: org_profile_result_meta
    write_meta: true
    normalize_payload_dates: false
```

`es_writeback_rules` 會自動鏡射到既有 `sql_writeback_rules`，因此 row merger 不必另外分支即可解析 stage merged output。

## Mapping 行為

1. 若 `es_apply_mapping: true` 且有 `mapping_file`，會先套到預設 `tgt_index`。
2. `es_output_mappings` 可套用多個 index 的 mapping 檔。
3. `es_writeback_rules` 可針對單一輸出欄位指定 `mapping_file`。
4. 若沒有 mapping 檔，會依 `output_type` 建立最小 mapping。
5. Elasticsearch 不能直接改既有欄位型別；若現有型別與 YAML 期望不同，請換欄位名稱或重建 index。

## 可選的舊版多維日期正規化

這個功能只服務舊版「多維日期」輸出結構，不是 ES 多階段框架的通用必備步驟。它會在寫回前掃描每筆 list item 中既定欄位，將可辨識的日期字串補成較適合 ES date 查詢與保留原文的欄位：

| 輸入位置 | 輸出/變更 | 說明 |
| --- | --- | --- |
| `Event.time` | 補 `Event.time_raw`、`Event.time_iso`、`Event.time_precision` | 保留原始字串，另寫入 ISO 日期與粒度。 |
| `date_range.start` / `date_range.end` | 補 `start_raw` / `end_raw` 與 `*_precision`，並把可解析值轉成 ISO 日期 | 方便 range 查詢；目前會覆寫 start/end 為 ISO 日期。 |
| `Event_Timeline[].date` | 補 `date_raw`、`date_iso`、`date_precision` | 保留時間線原始字串，另提供 date mapping 可查的 ISO 欄位。 |

目前只解析 `YYYY-MM-DD`、`YYYY-MM`、`YYYY` 三種格式；`YYYY-MM` 會補成該月 1 日，`YYYY` 會補成該年 1 月 1 日，並以 `time_precision` / `date_precision` 標示 `day`、`month`、`year`。因此它的泛用性是「中低」：適合舊版多維事件/時間線 schema，但不應預設套到任意任務。一般任務請讓 ES 直接保存 LLM JSON，若需要其他欄位轉換，應透過 `output_profile_plugins` / `output_profiles` 註冊可配置 transformer，而不是沿用這個舊版日期補欄。

若某些舊版多維日期輸出需要額外補 `*_raw` / `*_iso` / `*_precision`，可用下列參數明確啟用；預設不對任意任務做任務專屬轉換：

```yaml
es_payload_date_normalize_fields:
  - my_multidim_result
```

或在單一寫回規則中設定：

```yaml
normalize_payload_dates: true
```

若不設定上述參數，ES sink 只會解析 JSON 並原樣寫入，不會因欄位名稱套用任何特定任務邏輯。既有多維事件萃取 YAML（例如 `es_config.yaml`）已加入 `es_payload_date_normalize_fields: [multidim_event_json]`，因此原本的日期補欄流程會繼續生效。
