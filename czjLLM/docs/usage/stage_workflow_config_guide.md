# Multi-stage 任務設定 JSON 教學（Stage Workflow Config）

本文件提供「可直接套用」的設定範例，對應目前系統支援的多階段欄位：

> 建議檔案分層：  
> - `czjLLM/yaml/`：執行啟動設定（model、mode、source dir…）  
> - `czjLLM/stage_configs/`：多階段工作流設定（stages / routing / retries）
>
> 補充：多階段啟動時，`yaml` 可不填 `task`；程式會自動用第一個 stage 推導相容值。

### 建議檔名與放置位置（YAML）

1. **啟動 YAML（主設定）**  
   - 放在：`czjLLM/yaml/`  
   - 例如：`czjLLM/yaml/multi_stage_test_run.yaml`
2. **階段 YAML（stage workflow）**  
   - 放在：`czjLLM/stage_configs/`  
   - 例如：`czjLLM/stage_configs/multi_stage_pdf_en2zh_summary.yaml`
3. 主設定 YAML 內可用 `stage_config_path`（或你目前專案使用的等價欄位）指向 stage workflow 檔案。

### 啟動指令（範例）

> 以下以專案根目錄為目前工作路徑示意：

```bash
python -m czjLLM.czjLLM_TextProcessing --config czjLLM/yaml/multi_stage_test_run.yaml
```

若你是用現有專案腳本（例如批次或你既有 CLI 包裝），則把主設定 YAML 路徑改成同樣指向 `czjLLM/yaml/...` 即可。

- `name`: 階段名稱（不可重複）
- `task`: 該階段要給 LLM 的任務描述
- `task_key`: 從 `taskSetting` 字典取任務內容（可替代 `task`）
- `input_from`: 該階段輸入來源
  - `original`: 使用原文
  - `previous`: 使用前一階段輸出
  - `<stage_name>`: 使用指定階段輸出
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

---

## 8) YAML 設定速查（推薦實務寫法）

雖然上面示例多以 JSON 呈現，實務上你在本專案通常會寫成 YAML。

### 8.1 三階段範例（PDF 清整 → 翻譯 → 摘要）

```yaml
defaults:
  input_from: original
  persist_output: never
  max_attempts: 2

stages:
  - name: pdf_opt
    task_key: "PDF OPT-Instruction First"
    input_from: original
    persist_output: always

  - name: en_to_zh
    task_key: "Translation-toTWZH"
    input_from: previous
    persist_output: never

  - name: summarize
    task_key: "Summary-toTWZH"
    input_from: previous
    persist_output: final
```

### 8.2 `persist_output` 建議

- `always`：這一階段一定保留（適合關鍵中間態，像分類、清整、翻譯）。  
- `never`：不保留到最終持久化輸出（節省空間、減少中間檔）。  
- `final`：只在此階段是最後階段時保留（最常用於最終任務節點）。  

### 8.3 多階段輸出命名（目前行為）

1. **最終輸出檔**：仍保留來源子目錄結構，檔名會帶上任務後綴。  
2. **中間 `_stage_merges` 輸出**：也會盡量保留相對父層子目錄，避免不同來源資料夾混在一起。  
3. `_stage_merges` 內每個階段檔名格式：
   - `NN_<stage_name>_<task_key>.txt`（有 `task_key`）
   - `NN_<stage_name>.txt`（無 `task_key`）
4. 另會輸出 `manifest.json`，記錄各 stage 的 index/name/task_key/input_from/persist_output/merged_file/pieces。  

### 8.4 常見調整情境

- **不想保留翻譯中間態**：把該 stage 設 `persist_output: never`。  
- **想保留清整與翻譯供除錯**：這兩階段都設 `always`，摘要保留 `final`。  
- **長任務名怕檔名過長**：系統會自動做安全化與長度保護（截斷 + hash）。  
