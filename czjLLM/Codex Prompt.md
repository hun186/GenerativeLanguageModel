你正在修改一個既有 Python 專案：`czjLLM`

這是一個「高約束、分階段升級」的工程任務。

你不是在重寫系統。
你是在既有系統上：

1. 先建立可用的 multi-stage pipeline
2. 再在可控範圍內進行優化

---

# 📚 必須先閱讀（順序不可變）

1. AGENTS.md
2. ARCHITECTURE.md
3. docs/architecture/pipeline_architecture_upgrade.md
4. docs/implementation/codex_task_breakdown.md

若有衝突：

- 行為規則 → AGENTS.md
- 實作細節 → pipeline_architecture_upgrade.md
- 高階概念 → ARCHITECTURE.md
- 任務順序 → codex_task_breakdown.md

---

# 🎯 任務總目標

將既有系統升級為：

> 可組合的多階段 LLM Pipeline System

並以第一條 pipeline 作為落地案例：

`doc_type_aware_extraction`

流程：

Raw Text  
→ Chunk Summary  
→ DocType Classification  
→ Type-aware Extraction  
→ Type-aware Merger  
→ Output  

---

# 🧠 架構原則（必須遵守）

## 雙層架構

### Layer 1：`prompt_pipeline/`
負責：
- prompt construction
- LLM calls
- retry / fallback
- result parsing / handling

👉 這一層是既有 execution layer  
👉 必須重用，不可任意重寫

---

### Layer 2：`pipeline/`
負責：
- workflow orchestration
- PipelineContext
- step sequencing
- chunk/document routing
- merge strategy
- pipeline config

👉 這一層是新增 orchestration layer

---

# 🔥 核心規則

> `prompt_pipeline/` 負責執行  
> `pipeline/` 負責流程控制  

不得混用職責。

---

# 🚨 Hard Constraints（不可違反）

1. ❌ 不可破壞既有 extraction 行為
2. ❌ 不可破壞既有固定 JSON schema（對結構化抽取任務）
3. ❌ 不可將 prompt / LLM execution 邏輯搬進 `pipeline/`
4. ❌ 不可新增 `agent/` 架構
5. ❌ 不可建立平行系統
6. ❌ 不可做與本任務無關的大規模 cleanup
7. ❌ 不可隨意改動既有 public entry points
8. ❌ 不可創造新的不相容 schema
9. ❌ 不可使用真實 LLM API 作為測試依賴

---

# 🧪 實作前強制步驟（必須先做）

在寫任何程式碼前，你必須先：

## 1. 掃描 repo，找出以下位置

- LLM 呼叫位置
- prompt 組裝位置
- extraction 主流程位置
- chunk 切分位置
- merge 邏輯位置
- task config / pipeline config 位置
- 舊的 downstream 輸出處理位置（txt / DB / ES）

## 2. 明確列出

- 哪些 function / module 會被 reuse
- 哪些地方採用 wrapper，而不是 rewrite
- 哪些新增檔案是 orchestration layer
- 哪些既有檔案只做最小修改

👉 如果你沒有先做這一步，就不允許開始實作

---

# 🧱 目標結構（新增或擴充）

在 `czjLLM/` 下：

## `pipeline/`
- pipeline_context.py
- pipeline_types.py
- pipeline_config.py
- pipeline_utils.py
- pipeline_controller.py

### `pipeline/steps/`
- chunk_summary.py
- doc_type_classification.py
- extraction_multidim.py
- merge_multidim.py

### `pipeline/merge/`
- base_strategy.py
- merge_selector.py
- event_strategy.py
- interview_strategy.py
- profile_strategy.py
- issue_strategy.py
- report_strategy.py
- legal_strategy.py
- mixed_strategy.py

### `pipeline/config/`
- pipeline_config.yaml

---

## `prompt_pipeline/`
可新增或擴充，但只能限於：
- prompt assets
- prompt builder
- overlay support
- 輕量 integration glue

不可把 orchestration 邏輯寫進來。

---

# 📦 資料結構要求

## PipelineContext
至少包含：

- raw_text
- article_title
- article_date_iso
- chunks
- chunk_summaries
- doc_type_result
- extraction_results
- merged_result
- metadata

---

## StageResult
每個 step 必須回傳：

{
  "stage_name": ...,
  "success": ...,
  "data": ...,
  "debug": ...,
  "errors": ...
}

---

## PipelineOutput
最終對外輸出必須有 outer wrapper：

{
  "output_type": ...,
  "task_name": ...,
  "success": ...,
  "data": ...,
  "metadata": ...,
  "errors": ...
}

⚠️ 重要：
- `data` 必須保持原始任務輸出格式
- 不得強迫所有任務改為 JSON
- 對 structured extraction，既有 schema 必須保持不變

---

# ⚙️ Step 行為要求

## chunk_summary
- chunk-level
- 產生簡短摘要
- 可附 rough role
- 能用 mock / fake / 舊 prompt path 都可以

## doc_type_classification
- document-level only
- 必須基於：
  - article_title
  - head/tail
  - chunk summaries

輸出固定欄位：

- doc_type
- doc_type_confidence
- secondary_type
- has_primary_event
- routing_reason

## extraction_multidim
- chunk-level
- 必須 wrap 舊 extraction
- 不可重寫 extraction 核心
- 必須注入：
  - doc_type
  - doc_type_confidence
  - has_primary_event
  - routing_reason
  - article_title

## merge_multidim
- document-level
- 依 doc_type 選擇 merge strategy
- 保持原 schema
- 可使用 `_chunk_meta` 作內部 merge 輔助

---

# 🔀 Merge Strategy 要求

至少包含：

- event
- interview
- profile
- issue
- report
- legal
- mixed

要求：

- event → 選最穩定的核心事件
- interview → 保留採訪主幹
- profile → 避免假事件 timeline
- issue → 避免硬拼成單一事件
- report → 降低雜訊
- legal → 保持制度型結構簡潔
- mixed → 採保守策略

---

# 🧪 測試要求（本次必要交付，不可省略）

這個專案即使目前沒有 pytest，你也必須補最小可驗證測試。

## 原則

1. 測試不可依賴真實 LLM
2. 必須使用 mock / fake / stub LLM
3. 測試必須可穩定本地執行
4. 只補本次新增 pipeline 功能，不要妄圖一次補完整個舊專案

---

## 必須新增的測試能力

### A. pytest 基礎
若 repo 沒有 pytest：
- 建立最小 pytest 測試基礎
- 只針對本次新增 pipeline 功能

### B. mock LLM
若 repo 沒有現成 mock：
- 建立最小 mock LLM execution path
- 用於 chunk summary / doc type / extraction 測試

### C. smoke demo
必須提供最小可跑 demo script，例如：
- `run_demo.py`

---

## 至少要有以下測試

### 1. pipeline smoke test
驗證：
- `doc_type_aware_extraction` 可 end-to-end 跑完
- `success == True`

### 2. PipelineContext flow test
驗證：
- chunks 被建立
- chunk_summaries 被寫入
- doc_type_result 被寫入
- extraction_results 被寫入
- merged_result 被寫入

### 3. output wrapper test
驗證：
- output_type
- task_name
- success
- data
- metadata
- errors

### 4. schema compatibility test
針對 structured extraction，驗證：
- 既有 JSON schema 關鍵欄位仍在
- downstream 相容性未壞

### 5. merge strategy selection test
驗證：
- doc_type 對應到正確 merge strategy

---

## LLM 測試原則

LLM 任務可能具非決定性，因此：

- 不要做脆弱的全文字串完全比對
- 優先驗證結構、關鍵欄位、流程是否正確
- 對 mock LLM 可驗證固定輸出
- 對抽取測試重點應放在 schema 與 routing

---

# 🧩 兩階段策略（很重要）

## Phase 1：穩定落地（本次任務必須遵守）

目標：
- 建立 pipeline
- 保持相容
- 補測試
- 跑通第一條 pipeline

### Phase 1 限制
- 不可重寫既有核心 extraction
- 不可重寫 prompt_pipeline
- 只能用 wrapper / extension / overlay
- 不可做破壞性 refactor

---

## Phase 2：受控優化（只有在 Phase 1 完成且測試補齊後，才允許進入）

允許做的事：
- selective refactor
- merger logic optimization
- prompt overlay refinement
- chunking strategy optimization
- performance optimization
- code simplification

### Phase 2 前提
只有在以下條件成立時，才允許進行：
1. pipeline 已可跑
2. pytest / smoke tests 已存在
3. schema compatibility 已有驗證
4. 變更能被測試保護

---

## Phase 2 優化規則

即使進入 Phase 2，也仍然必須遵守：

- 不可破壞既有 schema
- 不可破壞既有 downstream
- 不可把 `prompt_pipeline/` 與 `pipeline/` 混在一起
- 只允許「可測試、可回滾、可比較」的優化

---

# 🧠 最小改動原則

優先順序：

1. ✅ 新增 `pipeline/` 模組
2. ✅ 包裝既有函式
3. ✅ 將新能力放在外層
4. ❌ 不要直接改爛舊 extraction
5. ❌ 不要亂搬檔案
6. ❌ 不要大改 import tree

---

# 🚫 明確禁止的錯誤

❌ 把 prompt 邏輯寫進 pipeline  
❌ 重寫 extraction engine  
❌ 為了新架構改掉舊 entry point  
❌ 建立第二套 schema  
❌ 建立 `agent/`  
❌ 忽略測試  
❌ 使用真實 API 當測試  
❌ 在沒有測試保護的情況下進行大規模優化  

---

# 🧪 實作順序（必須照做）

## Phase 1
1. repo 掃描與 reuse 分析
2. PipelineContext
3. pipeline_config / YAML loader
4. pipeline_controller
5. chunk_summary
6. doc_type_classification
7. extraction wrapper
8. merge strategies
9. merge_multidim
10. pipeline 註冊與跑通
11. mock LLM
12. pytest 最小測試
13. smoke demo

## Phase 2（只有在 Phase 1 完成後）
14. selective optimization
15. overlay refinement
16. merge quality improvement
17. optional clean refactor under test protection

---

# 📤 最後輸出必須包含

1. 新增檔案清單
2. 修改檔案清單
3. repo 掃描結果
4. reuse / wrapper 說明
5. pipeline 如何執行
6. 測試如何執行
7. TODO 清單
8. 若進入 Phase 2，列出哪些優化已做、哪些故意沒做

---

# 🧠 最重要的行為原則

當你不確定時，選擇：

- 最小改動
- 最大相容
- 可測試
- 可回滾

---

# FINAL RULE

你不是在重寫這個系統。

你是在：

> 先幫既有系統加上一個可測試、可回滾、可擴展的 pipeline 大腦  
> 然後只有在地基穩了之後，才允許做受控優化