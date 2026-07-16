# Multi-stage 任務設定 JSON 教學（Stage Workflow Config）

本文件提供「可直接套用」的設定範例，對應目前系統支援的多階段欄位：

> 建議檔案分層：  
> - `czjLLM/yaml/`：執行啟動設定（model、mode、source dir…）  
> - `czjLLM/stage_configs/`：多階段工作流設定（stages / routing / retries）
>
> 補充：多階段啟動時，`yaml` 可不填 `task`；程式會自動用第一個 stage 推導相容值。

- `name`: 階段名稱（不可重複）
- `task`: 該階段要給 LLM 的任務描述
- `task_key`: 從 `taskSetting` 字典取任務內容（可替代 `task`）
- `input_from`: 該階段輸入來源
  - `original`: 使用原文
  - `previous`: 使用前一階段輸出
  - `<stage_name>`: 使用指定階段輸出
  - 互動式多階段 builder 亦支援上述三種輸入來源（可指定 stage 名稱）
- `persist_output`: 輸出保存策略
  - `final`（預設）：只存最後階段
  - `always`：一定保存
  - `never`：不保存
- `max_attempts`: 該階段最大嘗試次數（超過後進入 error）
- `route_by`: 路由依據的來源階段名稱
- `route_map`: 依路由值切換任務模板（key -> task）
- `route_value_mode`: `route_map` value 的解讀方式
  - `task_key`（預設）：把 value 當 `taskSetting` key
  - `task`：把 value 當完整 task/prompt 文字
- `retry_source_on_route_miss`: 路由值不在 `route_map` 時，是否回退重跑 `route_by` 階段
- `debug_print_llm_io`: 是否印出該 stage「送往 LLM 的 prompt」與「LLM 回傳內容」（預設 `false`）
- `debug_print_max_chars`: 啟用 `debug_print_llm_io` 時，每段輸出最多顯示字元數（預設 `2000`；設定 `0` 或負數代表完整輸出）
  - 也可用 env 檔／環境變數全域覆蓋（適合臨時 debug，不改 YAML）：
    - `CZJLLM_DEBUG_PRINT_LLM_IO=true|false`
    - `CZJLLM_DEBUG_PRINT_MAX_CHARS=<int>`
    - `CZJLLM_ENV=<name>` 時會額外讀取 `.env.<name>`
  - env 檔優先序（低→高）：`.env` → `.env.<CZJLLM_ENV>` → `.env.local` → 系統環境變數（最高）

---

## 1) 最小可用（單階段）

```json
{
  "stages": [
    "抽取重點事實"
  ]
}
```

---

## 2) 串連式分析（翻譯 -> 摘要）

```json
{
  "stages": [
    {
      "name": "translate",
      "task": "把英文翻成中文",
      "input_from": "original",
      "persist_output": "always"
    },
    {
      "name": "summary",
      "task": "請根據中文內容輸出 5 點摘要",
      "input_from": "previous",
      "persist_output": "final"
    }
  ]
}
```

---

## 3) 路由式工作流（先分類，再套模板）

> 需求：先判斷類別，再依不同類別切換第二階段任務模板。  
> 第二階段輸入可設定為 `original`（直接用原文），但 task 內容依 `route` 輸出決定。

```json
{
  "stages": [
    {
      "name": "route",
      "task": "請只輸出分類代碼：A、B、C 其一",
      "input_from": "original",
      "persist_output": "always",
      "max_attempts": 3
    },
    {
      "name": "apply_template",
      "task": "fallback template",
      "input_from": "original",
      "route_by": "route",
      "route_map": {
        "A": "法務模板",
        "B": "財務模板",
        "C": "產品模板"
      },
      "route_value_mode": "task_key",
      "retry_source_on_route_miss": true,
      "max_attempts": 2,
      "persist_output": "final"
    }
  ]
}
```

---

## 4) 以 defaults 簡化配置（建議）

```json
{
  "defaults": {
    "input_from": "original",
    "persist_output": "never",
    "max_attempts": 2
  },
  "stages": [
    {"name": "route", "task": "輸出類別 A/B"},
    {
      "name": "apply",
      "task": "fallback",
      "route_by": "route",
      "route_map": {
        "A": "模板A",
        "B": "模板B"
      },
      "persist_output": "final"
    }
  ]
}
```

---

## 5) 人類友善 shorthand

系統支援以下簡寫：

1. `{"translate": "翻成中文"}`（等同於 `name=translate, task=翻成中文`）  
2. `from` 可替代 `input_from`  
3. `persist` 可替代 `persist_output`

範例：

```json
{
  "stages": [
    {"route": "只輸出 A/B/C"},
    {
      "name": "apply",
      "task": "fallback",
      "from": "original",
      "route_by": "route",
      "route_map": {
        "A": "模板A",
        "B": "模板B",
        "C": "模板C"
      },
      "persist": "final"
    }
  ]
}
```

---

## 6) 失敗與重試行為建議

1. 路由節點（分類）通常設定 `max_attempts: 2~3`。  
2. 路由下游（template）若強依賴路由值，建議 `retry_source_on_route_miss: true`。  
3. 重要中間輸出（如分類結果）建議 `persist_output: always`，方便追查。  
4. 最終輸出節點設 `persist_output: final`，避免保存過多中間噪音。  

---

## 7) 與既有 `taskSetting` 整合（你目前專案的主用法）

如果啟動後會載入很多任務到 `taskSetting` 字典，**可以直接讓 stage 對應 key**：

### 寫法 A（建議）：`task_key`

```json
{
  "stages": [
    {"name": "route", "task_key": "分類判定"},
    {"name": "apply_template", "task_key": "模板套用"}
  ]
}
```

### 寫法 B：`task` 用 `@taskSetting:<key>`

```json
{
  "stages": [
    {"name": "route", "task": "@taskSetting:分類判定"},
    {"name": "apply_template", "task": "@taskSetting:模板套用"}
  ]
}
```

### 寫法 C：`task` 留空，預設用 `stage.name` 對 `taskSetting`

```json
{
  "stages": [
    {"name": "分類判定"},
    {"name": "模板套用"}
  ]
}
```

> 所以回答你的問題：  
> `stage.name` **可以**等於 `taskSetting` 的 key（寫法 C），  
> 但更推薦用 `task_key`（寫法 A），可讀性和可維護性更好。  
> 路由時也建議 `route_map` value 使用 `taskSetting` key（`route_value_mode: task_key`）。

### 寫法 D：`prompt`（自訂提詞文字）與 `task_key`（任務鍵值）混用

```yaml
stages:
  - name: route
    prompt: |
      你是分類器。請判斷此文本是否屬於「組織實體介紹」。
      只輸出 JSON：{"route":"org"} 或 {"route":"other"}
  - name: extract
    task_key: Organization Profile Analyzer to json format
```

- `prompt`：這一階段直接使用你給的文字當「任務模板」來源。  
- `task_key`：這一階段改由 `taskSetting[task_key]` 解析模板。  
- YAML 的 `|` 是 **多行字串語法**，不是程式指令；會把換行保留在字串內容中。

> 補充：多階段執行時，`ctx.task` 會在呼叫該階段時暫時覆寫為「該階段實際 task（prompt 或 taskSetting 解析後內容）」，  
> 該階段完成後再還原，避免污染其他階段與全域狀態。

---

## 8) SQL / ES 多階段寫回建議（新增）

當 `mode=sql` 或 `mode=es` 並啟用多階段時，可用以下參數控制「寫回主欄位」與「JSON flatten」採用哪個階段輸出：

- `sql_writeback_source`
  - `combined`（預設）：沿用舊行為，使用 combine 最終檔
  - `stage`：改用指定 stage 的 merged 檔內容
- `sql_writeback_stage`
  - 可填 stage `name`、`task_key`，或 1-based 階段序號（例如 `2`）

範例（寫回第 2 階段）：

```yaml
mode: sql
stages:
  - name: route
    task_key: 分類判定
    persist_output: always
  - name: extract
    task_key: 事件抽取
    persist_output: always
  - name: final
    task_key: 最終整併
    persist_output: final

sql_writeback_source: stage
sql_writeback_stage: extract
```

> 若找不到對應 stage 或 manifest，系統會自動回退到 `combined`，確保不影響既有流程。

### SQL 多階段偵錯提示（2026-04）

- 若主表日誌出現  
  `combined(fallback:no_manifest;multistage_configured)`  
  代表你**有設定 `stages`**，但寫回階段找不到 `_stage_merges/.../manifest.json`。  
- 這通常表示執行路徑沒有真正產生 multi-stage manifest（例如實際僅跑單階段），可先用此訊號快速判斷「第二階段未落地」。

### SQL/SQLite 多階段執行說明（重用 txt merge 流程）

- 當 `mode: sql` 且 `stages` 數量大於 1，scheduler 會先完成切片後，直接呼叫 `process_prompt_and_merge()`（與 txt 模式同一套多階段 merge 邏輯）執行該列，再交由 row_merger 寫回。  
- 這樣可以避免在 `llm_stream_consumer` 另維護一套多階段派工分支，降低維護複雜度。若要臨時關閉可設定：`sql_enable_multistage_stream: false`。
- Stream 多階段支援 row/doc 層級的有界並行：producer 會依 `multistage_row_parallelism` / `sql_multistage_row_parallelism` / `stream_multistage_row_parallelism` 設定上限；若未設定，預設沿用既有單階段 LLM round 使用的 `ctx.n_process`；此值在初始化時會依可用 `base_url` endpoint pool 推導（on-premises 為可用 endpoint 數 × 2），而每次 LLM 呼叫仍會透過 `select_idle_ollama_url()` 從同一個 base_url pool 做租約式負載平衡。因多數部署是呼叫 Ollama / OpenAI-compatible API，派工主程式所在機器不一定看得到模型服務所在 GPU，因此不再用本機 GPU 數自動推估。若要覆寫遠端模型服務可承受的 row/doc 並行量，請明確設定其中一個平行度參數。此上限是為了避免一次送出過多長任務導致模型端排隊與 timeout。
- 若你希望寫回後自動清掉 prompt cache（避免 `cache/.../Success/0.txt` 殘留），可保留預設：  
  `cleanup_prompt_item_after_writeback: true`

### 8.1 進階：同一列同時寫回多個 stage 到不同 output 欄位

若你要「中間 stage + 最終 stage」都保留到 SQL / SQLite / Excel 主表，可使用：

```yaml
output_col: OPA_final
sql_writeback_rules:
  - output_col: OPA_route
    source: stage
    stage: route
  - output_col: OPA_extract
    source: stage
    stage: extract
  - output_col: OPA_final
    source: combined

# flatten 預設跟第 1 條 rule；可改為第 2 條（0-based）
sql_flatten_writeback_rule: 1
```

說明：
- `output_col` 仍是主輸出欄位（也作為 pending 判斷欄位）。
- `sql_writeback_rules` 會額外把對應來源寫到多個欄位；系統會自動補目標表欄位。
- 適用於遠端 SQL Server 與本地 SQLite（`mode: sql`），以及使用 ExcelSink 的表格寫回流程。

若要「多個來源各自 flatten（可各自關閉、各自欄位）」可改用：

```yaml
sql_flatten_writeback_rules:
  - writeback_rule: 0
    enabled: true
    allowed_output_fields: [route]
  - writeback_rule: 1
    enabled: true
    allowed_output_fields: [inputName, formalName, functionalDomain, keyFunctions]
    save_raw_input_when_flatten: true
```

補充：
- `writeback_rule` 是 `sql_writeback_rules` 的 0-based index。
- 若同時提供舊參數 `sql_flatten_writeback_rule` 與新參數 `sql_flatten_writeback_rules`，會優先使用新參數。
- 每個 flatten 來源會寫入對應子表：`{target_table}_{output_col}_flattened`。


### 8.2 JSON key 直接落主表欄位（便於 SQL 查詢）

若你的輸出 JSON 主要是給後續資料庫查詢使用，可開啟：

```yaml
sql_expand_json_to_columns: true
# sql_expand_json_prefix: json_   # 可選：避免撞欄位
```

行為：
- 會將 `sql_flatten_writeback_rule` 指向來源中的 JSON 物件 key 展開成主表欄位值。
- 只會展開 `allowed_output_fields` 列出的欄位（若有設定）。
- 系統會自動補齊主表欄位（搭配 schema ensure）。

### 8.3 整體收斂（新舊路徑一致）

- 舊版 `row_merger_watchdog_generic_OLD_1027` 已導向新版 `row_merger_watchdog_generic`，避免新舊邏輯分岔。
- CSV/Excel/SQL sink 的 `write_main()` 現在都可接受 `dict`（多欄位寫回），以對齊 `sql_writeback_rules` 輸出。

### 8.4 Mock LLM 模式（無模型也可跑 SQLite 多階段 E2E）

```yaml
model_spec: mock-local
mock_llm_mode: true
```

- `mock_llm_mode=true` 時，`call_llm_api()` 不會打模型端點，會直接把 TODO 產生對應 Success（路由任務輸出 `{"route":"org"}`，抽取任務輸出依 `allowed_output_fields` 產生 mock JSON）。
- 適合做流程驗證：切片 → stage dispatch → combine → writeback/flatten/分欄。

可直接參考：
- `czjLLM/yaml/sqlite_json_multistage_mock.yaml`
- `czjLLM/yaml/sqlite_json_multistage_prod_template.yaml`
- `czjLLM/yaml/sqlserver_multistage_prod_template.yaml`

---

## 8) SQL 模式 / Excel 模式：來源與目標設定（source/target 命名）

為了避免 `input/output`、`main_sheet` 等名稱混淆，建議在表格型流程統一使用：

- `source_*`：讀取來源
- `target_*`：寫回目標

### Excel / Table（CSV, XLSX）常用欄位

- `source_sheet_name`：來源工作表名稱（讀取用）
  - 若未設定且檔案是 Excel，系統會讀第一個工作表，並在終端機印出警告。
- `target_sheet_name`：結果寫回工作表名稱（寫入用）
  - 未設定時預設 `LLM_result`。
- `input_col`：來源文字欄位
- `output_col`：LLM 輸出欄位
- `primary_key`：主鍵欄位（可用 `row_id`）

### SQL 模式常用欄位（語意對照）

- `source`：來源資料（來源資料庫/資料表）
- `target`：寫回目標（目標資料庫/資料表）
- `input_col` / `output_col` / `primary_key`：欄位層設定
- `pending_recheck_shuffle_block_size`：可選；producer 讀到 pending 序列後，保留外部區塊順序、只在每個區塊內亂數重排。建議值如 `20`，可降低多主程序同順序掃描時的同步重複計算。
- `pending_recheck_shuffle_seed`：可選；設定後區塊內亂排可重現，便於測試與比對 log。

> 建議：若專案同時有 SQL 與 Excel 流程，命名層次盡量一致：
> - 資料來源/目標用 `source` / `target`
> - 欄位名才用 `input_col` / `output_col`

### Excel 範例（推薦）

```yaml
mode: table
input_excel_file: czjLLM/LLMSourcePool/excel_source/demo.xlsx
output_excel_file: czjLLM/LLMSourcePool/excel_source/demo_with_result.xlsx

source_sheet_name: RawData
target_sheet_name: LLM_result

input_col: File
output_col: File_result
primary_key: row_id
```
