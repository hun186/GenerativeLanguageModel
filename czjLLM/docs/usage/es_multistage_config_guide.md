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

## ES prefetch 設定與建議

`es_prefetch_buffer` 控制 ES pending iterator 是否用背景 thread 預先讀取候選文件：

```yaml
# 預設：關閉預取，使用直通 iterator
es_prefetch_buffer: 0
```

- `0` 或小於 `0`：關閉預取，producer 需要下一筆時才從 ES iterator 取件。
- 正整數：啟用預取，背景 thread 最多先把指定數量的 pending docs 放入本機 queue，例如 `5`、`20`、`50`。

對 LLM-heavy 任務（每列 LLM 呼叫通常需數秒以上）而言，整體瓶頸多半是 LLM 運算或遠端模型 API，而不是 ES 取件。因此預設關閉 prefetch，讓跨程序 pending 協作、dispatch-time pending recheck 與 ES 寫回可見性更容易收斂。尤其在同一台機器開多個 CMD/terminal 跑同一個 ES 任務檔時，大型 prefetch buffer 可能讓多個程序各自先拿到同一批舊 pending snapshot，增加重複派工、共享 Prompt cache 壓力，並放大 `TODO 未產生或為空` 這類排程競態訊息。

建議使用情境：

| 情境 | 建議 |
| --- | --- |
| LLM 每列需數秒以上、單機多視窗協作、共享 `WorkPool_czjLLM` / `Prompt/cache` | 維持 `es_prefetch_buffer: 0` |
| ES pending query 很慢，但 LLM endpoint 常閒置 | 試用小 buffer，例如 `es_prefetch_buffer: 5` 或 `20` |
| 單一程序、ES 在遠端 WAN、首批或下一批 pending 常等待很久 | 可逐步試 `20`、`50`，並觀察吞吐是否真的改善 |
| 多程序同跑同一批 ES rerun 任務 | 避免大型 buffer（例如 `1000`），優先使用 `0` 或很小的值 |

觀察重點：

1. 若關閉 prefetch 後 LLM endpoint 仍持續有工作、總處理時間沒有明顯變慢，表示 ES 取件不是瓶頸，應維持關閉。
2. 若終端反覆出現 `[prefetch] 首批 > ... 未到` 或 `[prefetch] 等下一批...`，且 LLM endpoint 明顯閒置，才考慮開小 buffer。
3. 若多視窗同跑時出現大量 `TODO 未產生或為空`，先關閉 prefetch，並可搭配：

```yaml
schedule_todo_wait_seconds: 120
pending_recheck_shuffle_block_size: 20
```

`schedule_todo_wait_seconds` 用於排除共享磁碟/目錄可見性延遲；`pending_recheck_shuffle_block_size` 可降低多個 producer 以相同順序掃描 pending docs 時的 lock-step 碰撞。


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

## 目前多維事件 mapping 與 `event_id` 關聯

`taskSetting_Enrichment.py` 目前使用 `config_es/schemas/InfoExtraction-MultiDim-mapping.yaml` 所描述的事件關聯 schema：

| 路徑 | ES 型別 | 契約 |
| --- | --- | --- |
| `multidim_event_json` | `nested` | 一篇來源文件可保存多個頂層分析物件。 |
| `multidim_event_json.Event` | `nested` | 必須是 array；每筆含唯一的 keyword `event_id`。 |
| `Person[].event_ids` | `keyword` array | 關聯人物所涉及的 `Event.event_id`。 |
| `Involved_Parties[].event_ids` | `keyword` array | 關聯單位、國家或組織所涉及的事件。 |
| `Impact[].event_ids` | `keyword` array | 關聯造成或共同構成該影響的事件。 |
| `Event_Timeline[].event_ids` | `keyword` array | 關聯該時間節點所描述的事件。 |
| `evidence_snippets[].event_ids` | `keyword` array | 關聯原文片段直接支持的事件。 |

所有 `event_ids` 只能引用同一個 `multidim_event_json` 元素內實際存在的 `Event.event_id`；可以同時引用多個事件，無法可靠歸屬時則是 `[]`。這個參照完整性由 `multidim_event` output profile 在寫回前驗證，ES mapping 本身不會提供外鍵約束。`taskSetting_Enrichment.py` 另要求每個 `Event` 至少被一筆 `evidence_snippets.event_ids` 引用，避免建立沒有原文證據的事件。

目前 Event 與時間線統一使用下列時間欄位：

| 路徑 | 欄位 |
| --- | --- |
| `Event[]` | `time_iso`、`time_raw`、`time_precision` |
| `Event_Timeline[]` | `time_iso`、`time_raw`、`time_precision` |

請勿再輸出舊版 `Event_Timeline.date_iso` / `date_raw` / `date_precision`。`time_iso` mapping 接受完整 ISO datetime 或 `YYYY-MM-DD`；`article_date_iso` 則保持文章層級的 `YYYY-MM-DD`。`multidim_event_json` 設為 `dynamic: strict`，因此欄位拼錯或沿用舊欄位會在 ES 寫入時直接失敗。

`Event` 從 `object` 改成 `nested` 屬於既有欄位型別變更，不能直接更新既有 index。上線時應建立套用新 mapping 的 index、reindex 舊資料，再切換 alias；若舊資料仍是單一 `Event` object 或沒有 `event_id` / `event_ids`，必須先轉換或重新抽取，不能只靠 reindex 自動補出關聯。

## 舊版多維日期正規化（僅供舊 schema）

這個功能只服務舊版「多維日期」輸出結構，不是 ES 多階段框架的通用必備步驟。它會在寫回前掃描每筆 list item 中既定欄位，將可辨識的日期字串補成較適合 ES date 查詢與保留原文的欄位：

| 輸入位置 | 輸出/變更 | 說明 |
| --- | --- | --- |
| `Event.time` | 補 `Event.time_raw`、`Event.time_iso`、`Event.time_precision` | 保留原始字串，另寫入 ISO 日期與粒度。 |
| `date_range.start` / `date_range.end` | 補 `start_raw` / `end_raw` 與 `*_precision`，並把可解析值轉成 ISO 日期 | 方便 range 查詢；目前會覆寫 start/end 為 ISO 日期。 |
| `Event_Timeline[].date` | 補 `date_raw`、`date_iso`、`date_precision` | 保留時間線原始字串，另提供 date mapping 可查的 ISO 欄位。 |

目前只解析 `YYYY-MM-DD`、`YYYY-MM`、`YYYY` 三種格式；`YYYY-MM` 會補成該月 1 日，`YYYY` 會補成該年 1 月 1 日，並以 `time_precision` / `date_precision` 標示 `day`、`month`、`year`。因此它的泛用性是「中低」，只適合仍採舊版多維事件/時間線 schema 的任務。現在的 `taskSetting_Enrichment.py` 與 `multidim_event` output profile 不會從 `time_raw` 推論日期，也不接受舊版 `Event_Timeline.date_*`；它們要求 task 直接產生已解析的 `time_iso` / `time_raw` / `time_precision`。一般任務請讓 ES 直接保存 LLM JSON；若需要其他欄位轉換，應透過 `output_profile_plugins` / `output_profiles` 註冊可配置 transformer，而不是沿用這個舊版日期補欄。

若某些舊版多維日期輸出需要額外補 `*_raw` / `*_iso` / `*_precision`，可用下列參數明確啟用；預設不對任意任務做任務專屬轉換：

```yaml
es_payload_date_normalize_fields:
  - my_multidim_result
```

或在單一寫回規則中設定：

```yaml
normalize_payload_dates: true
```

若不設定上述參數，ES sink 只會解析 JSON 並原樣寫入，不會因欄位名稱套用舊版日期補欄。對目前的新 schema，應使用 `output_profile: multidim_event` 進行結構、時間格式與 event reference 驗證；不要再啟用舊版 `normalize_payload_dates` 轉換。
