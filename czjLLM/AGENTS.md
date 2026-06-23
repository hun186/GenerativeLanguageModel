# Agent 工作指南

此檔提供 Codex / Agent 修改本 Repo 時的優先參考資訊。

目標：

* 減少不必要的全專案探索
* 降低 Token 消耗
* 提高修改效率
* 保持架構一致性
* 累積長期專案記憶

---

# 專案上下文載入（Project Context Loading）

在開始任何任務前，必須依序閱讀：

1. AGENTS.md
2. .codex/memory.md
3. .codex/architecture.md
4. .codex/api_contract.md
5. .codex/known_issues.md
6. .codex/decisions.md
7. .codex/backlog.md

若上述檔案或目錄不存在：

1. 建立 `.codex/` 目錄
2. 建立缺少的檔案
3. 以適當標題初始化內容

上述檔案視為本專案的長期記憶（Persistent Project Memory）。

若文件內容與目前程式碼不一致：

* 以程式碼為準
* 更新相關文件

---

# 開發原則（Development Principles）

優先理解：

* 專案目標
* 系統架構
* 資料流
* 模組邊界
* API 契約
* 已知限制

避免在未理解架構前進行大規模修改。

優先重用現有實作。

避免建立重複功能。

保持與既有程式風格一致。

---

# 開發流程（Development Workflow）

所有功能開發遵循：

1. 需求分析
2. 架構分析
3. 核心資料模型與介面設計
4. 功能實作
5. 驗證
6. 記憶更新

依專案類型可包含：

* Domain Model
* API
* Database
* Agent Workflow
* Batch Job
* CLI
* Frontend UI
* Infrastructure
* Docker
* CI/CD

僅實作本專案實際需要的組件。

不得為符合流程而新增不必要模組。

---

# 真實功能原則（Real Functionality First）

禁止以展示層、模擬資料或假結果掩蓋核心功能尚未完成的事實。

禁止使用：

* Mock Data
* Hard-coded Output
* Fake Success Message
* Stub Result

來宣稱功能已完成。

若因開發需要暫時保留未完成實作，必須明確標註：

STUB IMPLEMENTATION

並同步記錄於：

`.codex/backlog.md`

---

# 環境安裝與測試前置作業（Environment Setup）

在執行任何 pytest、API 啟動或功能驗證前，必須先確認已安裝專案相依套件。

請在專案根目錄執行：

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

---

# 驗證原則（Verification Requirements）

任務完成前必須提供驗證證據。

依專案性質至少包含一項：

* Unit Test
* Integration Test
* API Test
* SQL Query 驗證
* CLI 執行結果
* Batch Job 執行結果
* Agent Execution Log
* UI Static Test
* Playwright 測試
* Export File Validation
* Docker 啟動驗證
* curl 驗證

驗證結果需記錄於：

`.codex/memory.md`

---

# 無法驗證時的處理方式

若因以下原因無法完成驗證：

* Sandbox 限制
* 網路限制
* 權限限制
* 第三方服務限制
* 瀏覽器限制
* 套件安裝限制
* Docker 環境限制

必須：

1. 明確說明原因
2. 提供替代驗證方式
3. 更新 `.codex/known_issues.md`

未提供驗證說明前，不得宣稱任務完成。

---

# 專案記憶維護（Memory Maintenance）

每次完成任務後，必須同步更新專案記憶：

1. 更新 `.codex/memory.md`
2. 若架構、模組邊界或資料流有變更，更新 `.codex/architecture.md`
3. 若 API Contract 有變更，更新 `.codex/api_contract.md`
4. 若發現新的環境限制、錯誤或已知問題，更新 `.codex/known_issues.md`
5. 若產生新的設計決策或架構決策，更新 `.codex/decisions.md`
6. 若發現後續待辦事項或改善建議，更新 `.codex/backlog.md`

保留歷史紀錄。

一般任務僅追加內容。

一般任務不得覆蓋既有紀錄；但「記憶濃縮」是唯一例外，必須依下方濃縮機制保留可追溯歸檔後，才可重寫 active memory 檔案。

---

# 記憶濃縮機制（Memory Compaction）

長期記憶的目標是降低 token 消耗，而不是保存所有逐字流水帳。當記憶檔過長時，應把 active memory 維持為「目前仍有用的摘要」，並將完整歷史移入歸檔。

## 觸發條件

任一 `.codex/*.md` active memory 檔案符合下列條件之一時，必須在當次任務的「記憶更新」階段執行濃縮；若任務本身就是整理記憶，則應優先執行：

* 單檔超過 400 行。
* 單檔超過 40 KB。
* 單檔累積超過 20 個日期區塊或工作紀錄區塊。
* 已有多筆內容被目前程式碼、決策或 API contract 明確取代。
* 閱讀 active memory 時發現大量重複、過時或低價值執行細節。

## 濃縮流程

1. 建立 `.codex/archive/`（若不存在）。
2. 先將濃縮前全文保存到 `.codex/archive/<原檔名>-YYYYMMDD-HHMMSS.md`。
3. 重寫原 active memory 檔案為精簡版本，建議結構如下：
   * `# <檔案主題>`
   * `## Current Summary`：目前仍有效的結論、架構、限制或待辦。
   * `## Recent Changes`：保留最近 5～10 筆仍有參考價值的變更摘要。
   * `## Archived History`：列出歸檔檔名、濃縮時間與涵蓋範圍。
4. 濃縮時必須保留尚未解決的 backlog、known issues、STUB IMPLEMENTATION、API contract 與仍有效的架構決策。
5. 已失效內容不要逐字搬回 active memory；只需以「已被 X 取代」或「歷史細節已歸檔」記錄。
6. 濃縮完成後，在 `.codex/memory.md` 追加一筆濃縮紀錄，說明濃縮了哪些檔案、歸檔位置與驗證方式。

## 濃縮後的載入規則

* 一般任務只需閱讀 active memory 檔案，不需主動讀取 `.codex/archive/`。
* 只有在使用者要求追溯歷史、active memory 指向特定歸檔、或需要釐清被濃縮前的細節時，才讀取相關歸檔檔案。
* 濃縮後 active memory 目標大小：每個檔案盡量低於 200 行；若內容本質上較複雜，可保留必要資訊但要移除流水帳。
* 歸檔檔案僅供追溯，不列入例行「專案上下文載入」。

---

# 記錄原則

## memory.md

記錄：

* 任務目的
* 主要修改內容
* 驗證結果
* 重要結論

避免記錄：

* 大量重複日誌
* 無意義執行細節

---

## architecture.md

記錄：

* 系統架構
* 模組關係
* 資料流
* 專案目錄結構
* 核心元件說明

---

## api_contract.md

記錄：

* API 路由
* Request 格式
* Response 格式
* 重要資料結構
* 對外介面契約

若專案無 API，可保留空白並註明：

「本專案目前無 API Contract。」

---

## known_issues.md

記錄：

* 已知錯誤
* 環境限制
* 外部服務限制
* Sandbox 限制
* Docker 問題
* Playwright 問題
* 資料庫問題

---

## decisions.md

記錄：

* 架構決策
* 技術選型原因
* 不採用方案及理由
* 長期維護考量

---

## backlog.md

記錄：

* 尚未完成事項
* 技術債
* 改善建議
* 未完成的 STUB IMPLEMENTATION

---

# 安全規範

禁止將以下資訊寫入任何記憶檔案：

* API Key
* Access Token
* Password
* Cookie
* Private Key
* 憑證內容
* 個人敏感資料
* 機密資訊

如發現敏感資訊，應立即排除並避免寫入記憶系統。



## 專案概覽

- 本專案是以 Python 為主的多來源文件／表格資料處理與 LLM 多階段分析框架，支援 Excel、CSV、TXT、SQL / SQL Server、SQLite 與 Elasticsearch 等輸入來源。
- 核心流程包含：資料讀取、列資料前處理、prompt / task 設定、多階段 pipeline、LLM 呼叫、結果合併、JSON flatten 與匯出。
- 主要設定檔分散於 `yaml/`、`config/`、`config_sql/`、`config_es/`、`stage_configs/`、`task_configs/`、`modelConfig.py` 與 `model_configs/`。
- 多階段 pipeline 主要在 `pipeline/`；各資料來源模式分別在 `excel_mode/`、`csv_mode/`、`sql_mode/`、`es_mode/`、`tabular_mode/`。
- LLM / Ollama / OpenAI 相容服務與併發派工相關邏輯主要在 `infrastructure/`、`prompt_pipeline/`、`job_manager/` 與 `model_configs/`。
- 通用工具函式主要在 `utilities/`、`sql_utils/`、`cli_tools/`、`row_processors/` 與 `handlers/`。
- 專案目前不是 FastAPI web app；不要套用其他專案的 `api/`、dashboard、Swagger、Editor 表單等假設。

## 開發流程

所有功能開發遵循：

1. 需求分析
2. 架構與資料流分析
3. YAML / Python 設定契約確認
4. 資料來源模式或 pipeline 介面設計
5. 實作與最小範圍整合
6. 驗證（pytest、CLI dry run、小樣本資料或純函式測試）
7. 記憶更新

禁止直接修改輸出格式或設定範例來掩蓋 pipeline、資料讀取或 LLM 呼叫邏輯未完成問題。

禁止以 mock data 宣稱功能完成。

除非明確標註：
STUB IMPLEMENTATION

## 優先工作路徑

| 任務類型 | 優先查看 |
| --- | --- |
| 多階段 pipeline、階段流程、doc type aware extraction | `pipeline/pipeline_controller.py`, `pipeline/pipeline_config.py`, `pipeline/pipeline_context.py`, `pipeline/steps/`, `pipeline/config/` |
| 多階段結果合併策略 | `pipeline/merge/`, `pipeline/merge/merge_selector.py`, `pipeline/merge/base_strategy.py` |
| Prompt pipeline、LLM client、呼叫封裝 | `prompt_pipeline/`, `czjLLM_utils.py`, `modelConfig.py`, `model_configs/` |
| Ollama / OpenAI 相容端點、負載平衡、runtime 基礎設施 | `infrastructure/`, `job_manager/`, `env_examples/czjllm.env.example` |
| Excel 輸入模式 | `excel_mode/`, `yaml/excel_config.yaml`, `yaml/excel_json_multistage_config_with_score_route.yaml` |
| CSV / 一般表格輸入模式 | `csv_mode/`, `tabular_mode/`, `yaml/csv_config.yaml` |
| TXT / 文件輸入模式 | `handlers/handle_txt_file.py`, `yaml/txt_config.yaml`, `multi_stage.md` |
| SQL / SQLite / SQL Server 輸入與匯出 | `sql_mode/`, `sql_utils/`, `handlers/handle_sql_to_excel.py`, `handlers/export_sql_to_excel.py`, `config_sql/`, `yaml/sql_config.yaml`, `yaml/sqlite_json_config.yaml`, `yaml/sqlserver_multistage_prod_template.yaml` |
| Elasticsearch 模式與設定 | `es_mode/`, `config_es/`, `yaml/es_*.yaml`, `docs/usage/es_multistage_config_guide.md` |
| row processor、JSON flatten、欄位展平匯出 | `row_processors/`, `row_processors/json_flatten_export_cli.py`, `utilities/json_text_utils.py` |
| YAML / task / stage 設定調整 | `yaml/`, `task_configs/`, `stage_configs/`, `config/`, `docs/usage/` |
| Tokenizer 相關 | `tokenizers/` |
| 文件與流程圖 | `docs/`, `openai.md`, `multi_stage.md` |

## 降低 token 用量的搜尋原則

- 除非任務明確要求，避免掃描或讀取大型資料、備份或輸出目錄，例如：`data/`、`TestDoc_origin_backup/`、`.audit/`、`es_mode/runtime/`、`sql_mode/runtime/`。
- 除非任務明確要求，不要讀取 tokenizer 大檔：`tokenizers/**/tokenizer.json`。
- 檔名含 `複製`、`backup`、`before`、`Fake_No_Use` 的檔案通常是舊備份、重構前版本或測試用設定；除非任務明確要求，不要作為主要修改目標。
- 優先用 `rg` / `rg --files` 限定目錄搜尋，例如：`rg "pattern" pipeline sql_mode es_mode utilities`。
- 尋找設定範例時，優先查看 `yaml/`、`config_sql/`、`config_es/`、`env_examples/` 與 `docs/usage/`，不要一次展開整個專案。
- 不要使用 `ls -R` 或 `grep -R`。

## 常用測試與驗證指令

目前專案未固定提供單一測試入口；依修改範圍選擇最小可行驗證：

```bash
python -m pytest
```

若只改單一模組或新增測試，優先執行相關測試檔：

```bash
python -m pytest <test_file_or_test_dir>
```

語法層級快速檢查可用：

```bash
python -m compileall <changed_python_path>
```

CLI / 設定相關修改，優先以小樣本或 dry-run 類方式驗證對應 entry / CLI，例如：

```bash
python -m row_processors.json_flatten_export_cli --help
```

## 修改規範

- 優先做小範圍修改，避免跨多個不相關資料模式或 pipeline 階段重構。
- 修改 YAML 設定 schema、輸出 JSON shape、欄位命名或 merge strategy 時，請同步更新文件或範例設定，並補充最小驗證。
- 不要把 API key、token、密碼、私有 endpoint、資料庫連線字串或本機絕對路徑寫死到程式碼、YAML、文件或 `.codex/` 記憶檔。
- Python import 不要包在 try/except 裡；若需相容套件路徑，優先整理 import path 或集中於既有啟動流程處理。
- 修改會產生檔案輸出的流程時，優先使用 `utilities/atomic_io.py` 或既有原子寫入工具，避免半成品輸出。
- 修改多階段 pipeline 時，注意 `pipeline/pipeline_types.py` 的資料型別與各 `pipeline/steps/` 的輸入輸出契約。
- 修改 SQL / ES 模式時，不要假設外部服務在本機可用；若無法連線驗證，需提供不依賴外部服務的替代檢查。
- 若任務涉及 LLM 服務，預設外部模型端點可能不可用；優先驗證 prompt 組裝、設定解析、錯誤處理與純函式邏輯。
