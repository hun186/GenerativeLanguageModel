# ES `output_profile` 與多階段 Pipeline 的定位

## 1. 目前 ES 單階段模式的高層架構

目前既有 ES 模式本質上是單階段資料處理流程：

```text
Elasticsearch source index
→ 讀取一個 input_col，例如 rawInfo.content
→ 對該輸入執行一個 LLM task
→ 將 LLM 結果寫回一個 output_col，例如 multidim_event_json
→ 另外寫入 <output_col>_meta 作為 LLM 分析中繼資料
```

也就是說，ES mode 原本的核心不是多階段 orchestrator，而是：

1. `input_col`：從 ES 文件讀哪個欄位。
2. `task`：用哪個 task setting 產生 prompt / 執行 LLM。
3. `output_col`：把主結果寫回 ES 哪個欄位。
4. `<output_col>_meta`：附加處理時間、模型、任務、pipeline 標記等 metadata。

早期為了快速讓多維事件分析可跑，部分 ES sink 邏輯曾直接依賴 `output_col == "multidim_event_json"` 來套用事件 payload 正規化。這讓 ES 模式看起來像是只能服務事件分析。

## 2. `output_profile` 是什麼

`output_profile` 不是多階段路由，也不是 task 本身。

它是 **ES sink 在寫回前要不要套用某種 payload 正規化策略** 的設定，用來把原本寫死在程式碼裡的事件欄位判斷抽出來。

換句話說：

```text
task 決定 LLM 要做什麼
output_col 決定結果寫到哪裡
output_profile 決定寫回 ES 前如何整理 payload
stage_cfg / stages 決定未來多階段/路由怎麼串
```

## 3. 目前支援的 `output_profile`

| profile | 功能 |
| --- | --- |
| `auto` | 向後相容。若 `output_col` 是 `multidim_event_json` 或 `llm_result_json`，自動使用 `multidim_event`；否則等同 `none`。 |
| `none` | 不做任務特定 payload 正規化，適合一般文字、一般 JSON、分類、摘要、QA 等泛用任務。 |
| `json` | 語意上標記為泛用 JSON 輸出；目前寫回前不做事件正規化。 |
| `text` | 語意上標記為文字輸出；目前寫回前不做事件正規化。 |
| `multidim_event` | 套用多維事件輸出的 ES-friendly 正規化，例如補 `Event.time_iso` / `Event.time_precision`、`Event_Timeline[].date_iso` 等欄位。 |

## 4. 現在跑 `es_config.yaml` 時的 `output_profile`

`yaml/es_config.yaml` 目前設定：

```yaml
output_col: multidim_event_json
output_profile: auto
```

因此執行時的有效行為是：

```text
output_profile = auto
output_col = multidim_event_json
→ auto 推斷為 multidim_event
→ 寫回前套用多維事件 payload 正規化
```

這保留早期 `multidim_event_json` 的行為，但不再把判斷硬寫死成「只有這個欄位名才能做事件正規化」。未來若想把事件結果寫到其他欄位，可以設定：

```yaml
output_col: custom_event_json
output_profile: multidim_event
```

若要跑非事件任務，例如摘要、分類、QA、一般 JSON 抽取，則可以設定：

```yaml
output_col: summary_json
output_profile: json
```

或：

```yaml
output_col: answer_text
output_profile: text
```

## 5. `output_profile` 與多階段智慧路由的關係

`output_profile` 只處理「單一 stage 的結果要如何寫回 ES」。

多階段智慧路由應由 YAML 裡的 `stage_cfg` / `stages` 設定描述。這是為了對齊既有 `infer_multistage_task_hint(stage_cfg)` 的程式命名；`steps` 僅作為同義簡寫。ES 會把這些欄位正規化成同一個 `ctx.stage_cfg`。例如：

```text
stage_cfg:
  stages / router
→ 根據 route 選擇 zh / en / mixed / fallback
→ 執行對應 route stages
→ 將最終 stage output 寫入 final output_col
```

因此 ES 完整彈性的目標應分成兩層：

1. **Sink 層彈性**：用 `output_profile` 移除 `multidim_event_json` 寫死。
2. **Stage flow 層彈性**：用 `stage_cfg`、`stages`、`router`、`routes` 描述多階段智慧流路。

目前程式已能讀取 `stage_cfg`、`stages` / `steps`，並正規化保存到 `ctx.stage_cfg` 與 `<output_col>_meta`；真正依 route 執行多階段 stage 的 executor 是下一步工作。

## 6. 與 SQL / Excel / TXT 處理程式碼命名的關係

以目前程式碼來看，既有多階段提示推導函式已使用 `infer_multistage_task_hint(stage_cfg)` 這個命名，因此 ES 也應直接沿用 `stage_cfg`，而不是另創 `pipeline_config`。SQL / Excel / TXT 的執行狀態仍主要掛在同一個 `ctx` 上，並交給既有 `run_pipeline(ctx, pending_iter, ...)` 執行。

因此 ES 這邊的中性內部命名是：

```text
ctx.stage_cfg
```

它代表「由 YAML 宣告的 stage flow」。

目前建議的概念對應是：

| 層次 | 建議命名 | 說明 |
| --- | --- | --- |
| 執行入口 | `run_pipeline(ctx, ...)` | 既有 SQL/Excel/ES 共用的批次處理入口命名。 |
| Runtime context | `ctx` | 各模式共同承載工作設定與狀態。 |
| YAML stage flow | `ctx.stage_cfg` | 新增的「多階段流程宣告」中性名稱。 |

## 7. ES index mapping 與各 stage index 的定位

ES index mapping 有在專案程式裡，而且目前分成兩層：

1. **完整 mapping 檔**：例如 `config_es/schemas/InfoExtraction-MultiDim-mapping.yaml`，可由 ES config 的 `es_apply_mapping: true` + `mapping_file` 指定。
2. **最小備援 mapping**：若沒有 mapping 檔，`ensure_schemas_es()` 會至少替目前的 `output_col` 建立 `nested` / `object` 欄位，並替 `<output_col>_meta` 建立常用 metadata 子欄位。

目前單階段 ES flow 只會對 adapter 的 `tgt_index` 套用一次 mapping。也就是：

```text
adapter.cfg["tgt_index"]
→ ensure_schemas_es()
→ apply_mapping_file(tgt_index, mapping_file)
→ 確保 output_col / meta 欄位存在
```

若要擴充成多階段，每個 stage 應可以宣告自己的 ES 寫入位置與 mapping，例如：

```yaml
stage_cfg:
  routes:
    zh:
      stages:
        - name: zh_extraction
          output_col: multidim_event_json
          output_profile: multidim_event
          es:
            src_index: news-source
            tgt_index: news-zh-result
            mapping_file: czjLLM/config_es/schemas/InfoExtraction-MultiDim-mapping.yaml
```

`stage_cfg` normalizer 已提供 `collect_stage_es_bindings(stage_cfg, ...)`，用來把 router / route stages 裡的 `es.src_index`、`es.tgt_index`、`output_col`、`output_profile`、`mapping_file` 收集成清單。它目前只做「宣告收集」，不直接建立 index 或執行 stage；未來 multistage executor 應使用這個 binding 清單，對每個 stage：

1. 建立或選擇該 stage 的 adapter / sink。
2. 對該 stage 的 `tgt_index` 套用 `mapping_file`。
3. 依該 stage 的 `output_col` / `output_profile` 寫回結果。

因此目前已具備「把不同 stage 的 index/mapping 資訊放進 stage_cfg」的結構，但真正逐 stage 套 mapping、逐 stage 寫不同 index，仍屬下一步 executor 工作。


## 8. `es_json_multistage_langroute_config.yaml` 目前實際會做什麼

`yaml/es_json_multistage_langroute_config.yaml` 目前是 **多階段路由設計樣板 + 單階段相容執行設定**，不是已經會真正分支執行的 multistage executor 設定。

如果現在直接拿這份 YAML 跑現有 ES mode，實際流程仍是：

```text
讀 input_col = rawInfo.content
→ 執行 task = InfoExtraction-MultiDim-SQLFriendly-to json format
→ 寫 output_col = multidim_event_json
→ output_profile = auto，因此因 output_col 推斷為 multidim_event 正規化
→ 將 stage_cfg.name/version/enabled 等資訊寫入 <output_col>_meta
```

也就是說，目前不會真的先跑 `router`，也不會依 `routes.zh` / `routes.en` / `routes.mixed` / `routes.fallback` 分支執行不同 stage。

這份 YAML 的 `stage_cfg` 區塊現在有兩個用途：

1. **先把未來的多階段路由 DSL 固定下來**：包含 `router`、`routes`、各 route 的 `stages`、每個 stage 的 `output_col` / `output_profile`。
2. **先把未來的 ES index/mapping 宣告放到每個 stage**：例如每個 stage 的 `es.src_index`、`es.tgt_index`、`es.mapping_file`。這些可由 `collect_stage_es_bindings(stage_cfg, ...)` 收集，但目前尚未由 executor 套用。

因此，這份 YAML 目前的價值是「宣告與驗證未來多階段 ES 設計形狀」，同時仍可用單階段欄位跑舊流程；真正 router/routes 執行與逐 stage index/mapping 套用，是下一步 executor 工作。


## 9. 每個 stage 是否一定要寫入 ES？

不一定。ES 不應強制每個 stage 都寫一個 doc 回資料庫。

目前單階段 `ESSink.write_main()` 預設仍會寫入 `output_col`，以維持既有 ES 行為；但 sink 現在支援 `ctx.write_output = False` / `ctx.es_write_output = False`，設定後會略過主結果寫入，不會把該次結果 buffer 成 ES update action。

對未來 multistage executor，建議在每個 stage 宣告：

```yaml
stage_cfg:
  router:
    name: language_route
    output_col: route_lang_json
    write_output: false   # 只在記憶體中供後續 route 判斷，不寫 ES
  routes:
    zh:
      stages:
        - name: zh_extraction
          output_col: multidim_event_json
          write_output: true
```

`collect_stage_es_bindings(stage_cfg, ...)` 會保留每個 stage 的 `write_output` 宣告。未來 executor 可依這個欄位決定：

- `write_output: false`：stage 結果只留在 pipeline context / memory，供下一階段使用。
- `write_output: true`：stage 結果寫入該 stage 指定的 `tgt_index` / `output_col`。

因此 ES 模式可以做到和 SQL / Excel 類似的「每階段決定是否保存輸出」；只是目前既有單階段 runner 尚未執行多階段，所以逐 stage 保存策略要等 multistage executor 實作後才會完整生效。
