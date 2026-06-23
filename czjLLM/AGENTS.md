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

- 本專案是 FastAPI + Elasticsearch 的 RAG / agent 系統。
- API 與 HTTP endpoint 主要在 `api/`。
- Agent、retrieval、evidence 主要在 `agent/`；資料匯入與 ETL 主要在 `data_ingestion/`。
- 設定檔主要在 `config/`。
- 測試主要在 `tests/`。

## 開發流程

所有功能開發遵循：

1. 需求分析
2. 架構分析
3. API / Domain 設計
4. Backend 實作
5. Frontend 實作
6. 驗證
7. 記憶更新

禁止直接修改前端來掩蓋後端未完成問題。

禁止以 mock data 宣稱功能完成。

除非明確標註：
STUB IMPLEMENTATION
## 優先工作路徑

| 任務類型 | 優先查看 |
| --- | --- |
| Chat completion / 對話 API | `api/routers/chat.py`, `api/services/sessions.py`, `agent/` |
| FastAPI app 啟動、middleware、路由掛載 | `api/main.py`, `api/routers/` |
| Elasticsearch 查詢、證據整理 | `agent/es/`, `agent/data_agent/` |
| SQL Server 匯入 Elasticsearch | `data_ingestion/sql_to_es/ingest_sql.py`, `config/sql_import/` |
| Excel 匯入 SQL Server | `data_ingestion/excel_to_sql/`, `config/excel_to_sql/` |
| Excel 匯入監控 dashboard | `data_ingestion/excel_to_sql/dashboard.py`, `api/routers/excel_to_sql.py`, `api/static/excel_to_sql_dashboard.html` |
| Word / DOCX 匯出 | `api/services/export_word_service.py`, `api/core/presenters/docx/` |
| Editor 表單與稽核 | `api/routers/editor.py`, `api/services/editor_form_config.py`, `api/services/editor_audit.py`, `config/editor_form.default.json` |

## 降低 token 用量的搜尋原則

- 除非任務明確要求，避免掃描或讀取 `data/`；此目錄包含大量資料檔。
- 除非任務明確要求，避免修改 vendored Swagger UI 靜態檔：`api/static/swagger-*`、`api/static/oauth2-redirect.html`。
- 檔名含 `複製` 的檔案通常是舊備份或重構前版本；除非任務明確要求，不要作為主要修改目標。
- 優先用 `rg` / `rg --files` 限定目錄搜尋，例如：`rg "pattern" api agent tests`。
- 不要使用 `ls -R` 或 `grep -R`。

## 常用測試指令

```bash
pytest tests
```

Excel 匯入與 dashboard 相關：

```bash
pytest tests/test_excel_to_sql_dashboard_static.py tests/test_dashboard_filters.py tests/test_ingest_diagnostics.py tests/test_ingest_insert_fallback.py tests/test_audit.py tests/test_sql_utils.py
```

## 修改規範

- 優先做小範圍修改，避免跨多個不相關模組重構。
- API response shape 或前端 dashboard 行為改變時，請同步補測試或更新既有測試。
- 不要把密碼、token、私有連線資訊寫死到程式碼或文件。
- Python import 不要包在 try/except 裡。
- 修改靜態 web UI 且可執行時，若環境允許請截圖驗證。
