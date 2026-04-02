# Codex Prompt（深度整合版）

你正在修改一個既有 Python 專案：`czjLLM`

這不是一般的小型重構。
這是一個「高約束、分階段落地、但目標必須做到深度整合」的工程任務。

你不是在重寫系統。
你是在既有系統上：

1. 先建立可用且相容的 multi-stage pipeline
2. 再把原本被簡化掉的深度整合能力補回來
3. 最後讓整體具備可測試、可觀測、可回滾、可擴展的 production-grade orchestration 能力

---

# 📚 必須先閱讀（順序不可變）

1. `AGENTS.md`
2. `ARCHITECTURE.md`
3. `docs/architecture/pipeline_architecture_upgrade.md`
4. `docs/implementation/codex_task_breakdown.md`
5. 與 pipeline / execution / merge / output 相關的既有程式碼

若有衝突：

- 行為規則 → `AGENTS.md`
- 實作細節 → `pipeline_architecture_upgrade.md`
- 高階概念 → `ARCHITECTURE.md`
- 任務順序 → `codex_task_breakdown.md`
- 深度整合補強要求 → 本 prompt

---

# 🎯 任務總目標

將既有系統升級為：

> 可組合、可路由、可併發、可監控、可恢復、可擴展的多階段 LLM Pipeline System

並以第一條 pipeline 作為落地案例：

`doc_type_aware_extraction`

基礎流程：

`Raw Text`  
→ `Chunk Summary`  
→ `DocType Classification`  
→ `Type-aware Extraction`  
→ `Type-aware Merger`  
→ `Output`

但這次**不接受只有 demo 級串接**。
你必須把原本簡化掉的深度整合能力一起納入設計與實作，包括：

- chunk / document 層級的明確派工
- 可控的多工平行執行
- stage-level / task-level 監控資訊
- retry / fallback / partial failure handling
- routing / dispatch / merge 的一致上下文
- 可測試的 orchestration hooks
- 對既有 downstream 保持相容

---

# 🧠 架構原則（必須遵守）

## 雙層架構

### Layer 1：`prompt_pipeline/`
負責：
- prompt construction
- LLM calls
- retry / fallback（單步執行層級）
- result parsing / handling
- provider / adapter / model interaction

👉 這一層是既有 execution layer  
👉 必須重用，不可任意重寫  
👉 可做輕量擴充，但不可把 orchestration 中樞塞進來

---

### Layer 2：`pipeline/`
負責：
- workflow orchestration
- PipelineContext
- step sequencing
- chunk/document routing
- dispatch / worker coordination
- merge strategy
- pipeline config
- run state / stage state / execution metadata
- monitoring / metrics / debug traces

👉 這一層是新增 orchestration layer  
👉 深度整合能力必須落在這一層  
👉 但不可變成第二套 execution engine 去重寫 `prompt_pipeline/`

---

# 🔥 核心規則

> `prompt_pipeline/` 負責執行  
> `pipeline/` 負責流程控制、派工、整合、監控  
> 二者必須清楚分層，不得混職責

你要做的是：

- **保留既有 execution layer**
- **新增真正可運作的 orchestration brain**
- **讓多階段流程不只是串起來，而是能被管理、被觀測、被驗證**

---

# 🚨 Hard Constraints（不可違反）

1. ❌ 不可破壞既有 extraction 行為
2. ❌ 不可破壞既有固定 JSON schema（對結構化抽取任務）
3. ❌ 不可將 prompt / LLM execution 核心邏輯搬進 `pipeline/`
4. ❌ 不可新增 `agent/` 架構
5. ❌ 不可建立平行且互不相容的第二套系統
6. ❌ 不可做與本任務無關的大規模 cleanup
7. ❌ 不可隨意改動既有 public entry points
8. ❌ 不可創造新的不相容 schema
9. ❌ 不可使用真實 LLM API 作為測試依賴
10. ❌ 不可只做單線串接就宣稱完成深度整合
11. ❌ 不可把多工 / 監控 / 派工需求降格成純註解或 TODO
12. ❌ 不可為了並行而破壞 deterministic testability
13. ❌ 不可引入重量級外部基礎設施依賴（例如 Celery / Kafka / Redis）作為此次落地前提

---

# ✅ 這次必須補上的深度整合能力

本次版本**不是簡化版 pipeline**。
至少要在 repo 內落地以下能力，而且要真的可執行、可測試：

## 1. 派工 / Dispatch
必須明確區分：
- document-level stage
- chunk-level stage
- merge-level stage

並提供：
- chunk 任務建立
- chunk 任務派發
- chunk 任務結果回收
- stage 間資料回填到 `PipelineContext`

## 2. 多工平行 / Controlled Concurrency
至少要支援：
- chunk-level bounded concurrency
- 可由 config 控制 worker 數 / concurrency 數
- 預設保守值
- 測試模式可切單工 deterministic mode

實作上可以用：
- `concurrent.futures`
- `asyncio`（若 repo 現況適合）
- thread pool / process pool / sync fallback

但原則是：
- 先選與 repo 最相容、最小侵入的方式
- 不可因為追求炫技而大改整個 execution model

## 3. 監控 / Observability
至少要有：
- pipeline run id
- stage start / end
- success / failure / partial success
- 每 stage 耗時
- chunk 任務統計
- retry 次數
- fallback 是否發生
- merge strategy 選擇結果

這些資訊至少要能進入：
- `metadata`
- `debug`
- logger / structured logs（若 repo 已有 logger）

## 4. 失敗恢復 / Failure Handling
至少要支援：
- 單 chunk 失敗不必然炸掉整個 document pipeline
- 可設定 fail-fast 或 best-effort
- 可回傳 partial errors
- merge 前可過濾失敗 chunk
- output wrapper 要保留 errors 與 execution metadata

## 5. 路由 / Routing Context Consistency
`doc_type_classification` 的結果不能只是給下一步看一眼。
必須作為：
- extraction overlay context
- merge strategy selection 依據
- debug / observability 資訊的一部分
- 可測試的 routing 決策輸出

## 6. 可設定化 / Configurability
至少要有：
- pipeline registry
- pipeline YAML/config loader
- per-stage enable/disable
- concurrency config
- retry config
- fail-fast / best-effort config
- merge strategy mapping config（可程式內建 + 設定覆蓋）

## 7. 深度整合但不失相容
意思是：
- 舊 extraction core 繼續存在
- 舊 downstream schema 繼續可吃
- 舊 entry point 可最小改動接入 pipeline
- 新 orchestration 能包住舊能力，而不是另起爐灶

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
- 既有 logger / metrics / debug hooks
- 任何已存在的 thread / async / batch 機制

## 2. 明確列出

- 哪些 function / module 會被 reuse
- 哪些地方採用 wrapper，而不是 rewrite
- 哪些新增檔案是 orchestration layer
- 哪些既有檔案只做最小修改
- 哪些地方需要 integration glue
- 哪些地方可安全插入 monitoring / execution metadata

## 3. 明確辨識哪些深度整合能力目前缺失
至少指出：
- 哪些多工能力原本不存在 / 失效 / 被簡化
- 哪些監控能力目前不足
- 哪些派工節點目前只是直串
- 哪些錯誤處理目前不足以支撐 production-like pipeline

👉 如果你沒有先做這一步，就不允許開始實作

---

# 🧱 目標結構（新增或擴充）

在 `czjLLM/` 下至少建立或擴充：

## `pipeline/`
- `pipeline_context.py`
- `pipeline_types.py`
- `pipeline_config.py`
- `pipeline_utils.py`
- `pipeline_controller.py`
- `pipeline_registry.py`
- `pipeline_monitor.py`
- `pipeline_dispatcher.py`
- `pipeline_runner.py`（若需要，作為 orchestration façade）

### `pipeline/steps/`
- `chunk_summary.py`
- `doc_type_classification.py`
- `extraction_multidim.py`
- `merge_multidim.py`

### `pipeline/merge/`
- `base_strategy.py`
- `merge_selector.py`
- `event_strategy.py`
- `interview_strategy.py`
- `profile_strategy.py`
- `issue_strategy.py`
- `report_strategy.py`
- `legal_strategy.py`
- `mixed_strategy.py`

### `pipeline/config/`
- `pipeline_config.yaml`

---

## `prompt_pipeline/`
可新增或擴充，但只能限於：
- prompt assets
- prompt builder
- overlay support
- execution adapter glue
- mockable execution seams

不可把 orchestration / scheduler / dispatcher 主體寫進來。

---

# 📦 資料結構要求

## PipelineContext
至少包含：

- `run_id`
- `pipeline_name`
- `raw_text`
- `article_title`
- `article_date_iso`
- `chunks`
- `chunk_tasks`
- `chunk_summaries`
- `doc_type_result`
- `extraction_results`
- `merged_result`
- `metadata`
- `debug`
- `errors`
- `stage_status`
- `timings`

---

## StageResult
每個 step 必須回傳：

```json
{
  "stage_name": "...",
  "success": true,
  "data": {},
  "debug": {},
  "errors": []
}
```

可額外擴充：
- `duration_ms`
- `stats`
- `partial_success`
- `retry_count`

---

## ChunkTask / ChunkResult
至少要有：

```json
{
  "chunk_id": "...",
  "chunk_index": 0,
  "payload": "...",
  "stage_name": "...",
  "status": "pending|running|success|failed",
  "attempt": 1,
  "metadata": {}
}
```

以及對應結果結構，供 dispatcher / monitor / merge 使用。

---

## PipelineOutput
最終對外輸出必須有 outer wrapper：

```json
{
  "output_type": "...",
  "task_name": "...",
  "success": true,
  "data": {},
  "metadata": {},
  "errors": []
}
```

⚠️ 重要：
- `data` 必須保持原始任務輸出格式
- 不得強迫所有任務改為 JSON
- 對 structured extraction，既有 schema 必須保持不變
- `metadata` 必須包含本次 orchestration 的必要執行資訊，但不能污染既有下游 schema 主資料區

---

# ⚙️ Step 行為要求

## `chunk_summary`
- chunk-level
- 產生簡短摘要
- 可附 rough role
- 可使用 mock / fake / 舊 prompt path
- 必須支援 chunk-level dispatch
- 必須可被 bounded concurrency 執行
- 必須回報 chunk stats / failures

## `doc_type_classification`
- document-level only
- 必須基於：
  - `article_title`
  - head / tail
  - chunk summaries
- 輸出固定欄位：
  - `doc_type`
  - `doc_type_confidence`
  - `secondary_type`
  - `has_primary_event`
  - `routing_reason`
- 此結果必須寫入 context 並參與後續 routing / merge / debug

## `extraction_multidim`
- chunk-level
- 必須 wrap 舊 extraction
- 不可重寫 extraction 核心
- 必須注入：
  - `doc_type`
  - `doc_type_confidence`
  - `has_primary_event`
  - `routing_reason`
  - `article_title`
- 必須支援 chunk-level dispatch / bounded concurrency
- 必須支援 partial failure handling
- 必須保留既有 schema compatibility

## `merge_multidim`
- document-level
- 依 `doc_type` 選擇 merge strategy
- 保持原 schema
- 可使用 `_chunk_meta` 作內部 merge 輔助
- merge 前需能看到成功 / 失敗 chunk 狀態
- merge 後需輸出策略選擇與關鍵 debug 資訊

---

# 🔀 Merge Strategy 要求

至少包含：
- `event`
- `interview`
- `profile`
- `issue`
- `report`
- `legal`
- `mixed`

要求：
- `event` → 選最穩定的核心事件
- `interview` → 保留採訪主幹
- `profile` → 避免假事件 timeline
- `issue` → 避免硬拼成單一事件
- `report` → 降低雜訊
- `legal` → 保持制度型結構簡潔
- `mixed` → 採保守策略

此外：
- merge selector 必須可測試
- merge strategy mapping 必須可配置或可覆蓋
- 必須保留 internal debug meta 但不污染對外 schema

---

# 🖥️ Dispatcher / Worker / Monitoring 要求

這是本次「深度整合」的核心，不可省略。

## Dispatcher
至少要有：
- 建立 chunk 任務清單
- 根據 stage 分派 worker 執行
- 收斂結果
- 將結果依 chunk index 或 chunk id 排回穩定順序
- 對失敗任務產生錯誤紀錄

## Worker Execution Model
至少要支援：
- sync mode（測試 / fallback）
- bounded parallel mode（正式執行）

## Monitoring / Trace
至少要留下：
- run-level trace
- stage-level trace
- chunk-level counters
- success / fail counts
- latency stats
- retry / fallback stats

## Determinism
- 測試預設需可切成單工 deterministic mode
- 若採平行執行，結果收斂必須保序或至少可穩定排序

---

# 🧪 測試要求（本次必要交付，不可省略）

這個專案即使目前沒有 `pytest`，你也必須補最小可驗證測試。

## 原則

1. 測試不可依賴真實 LLM
2. 必須使用 mock / fake / stub LLM
3. 測試必須可穩定本地執行
4. 只補本次新增 pipeline 功能，不要妄圖一次補完整個舊專案
5. 必須涵蓋深度整合能力，而不是只測 happy path

---

## 必須新增的測試能力

### A. pytest 基礎
若 repo 沒有 `pytest`：
- 建立最小 pytest 測試基礎
- 只針對本次新增 pipeline 功能

### B. mock LLM
若 repo 沒有現成 mock：
- 建立最小 mock LLM execution path
- 用於 `chunk_summary` / `doc_type` / `extraction` 測試

### C. smoke demo
必須提供最小可跑 demo script，例如：
- `run_demo.py`
- `run_pipeline_demo.py`

---

## 至少要有以下測試

### 1. pipeline smoke test
驗證：
- `doc_type_aware_extraction` 可 end-to-end 跑完
- `success == True`

### 2. PipelineContext flow test
驗證：
- `chunks` 被建立
- `chunk_tasks` 被建立
- `chunk_summaries` 被寫入
- `doc_type_result` 被寫入
- `extraction_results` 被寫入
- `merged_result` 被寫入

### 3. output wrapper test
驗證：
- `output_type`
- `task_name`
- `success`
- `data`
- `metadata`
- `errors`

### 4. schema compatibility test
針對 structured extraction，驗證：
- 既有 JSON schema 關鍵欄位仍在
- downstream 相容性未壞

### 5. merge strategy selection test
驗證：
- `doc_type` 對應到正確 merge strategy

### 6. dispatcher bounded concurrency test
驗證：
- chunk tasks 可被 dispatcher 正確派發
- 可設定 `max_workers`
- 結果回收後順序穩定

### 7. partial failure handling test
驗證：
- 單一或部分 chunk 失敗時
- pipeline 可在 best-effort 模式繼續
- `errors` 與 `metadata.stats` 正確反映

### 8. fail-fast mode test
驗證：
- 在 fail-fast 模式下發生關鍵錯誤時
- pipeline 會依設定中止或回傳對應錯誤

### 9. monitor metadata test
驗證：
- stage timings
- retry stats
- merge strategy
- run id
- chunk success/failure counts

### 10. deterministic test mode
驗證：
- 在單工模式下測試結果穩定
- 平行與單工模式輸出 schema 相容

---

## LLM 測試原則

LLM 任務可能具非決定性，因此：

- 不要做脆弱的全文字串完全比對
- 優先驗證結構、關鍵欄位、流程是否正確
- 對 mock LLM 可驗證固定輸出
- 對抽取測試重點應放在 schema、routing、dispatch、monitoring、error handling

---

# 🧩 實作策略：兩階段，但 Phase 1 就要有深度整合骨架

## Phase 1：穩定落地 + 深度整合骨架到位（本次任務必須遵守）

目標：
- 建立 pipeline
- 保持相容
- 補測試
- 跑通第一條 pipeline
- 將 dispatch / monitoring / bounded concurrency / failure handling 的核心骨架落地

### Phase 1 限制
- 不可重寫既有核心 extraction
- 不可重寫 `prompt_pipeline`
- 只能用 wrapper / extension / overlay / orchestration
- 不可做破壞性 refactor
- 但不得以「先留 TODO」取代真正的 dispatcher / monitor / config / failure model

---

## Phase 2：受控優化（只有在 Phase 1 完成且測試補齊後，才允許進入）

允許做的事：
- selective refactor
- merger logic optimization
- prompt overlay refinement
- chunking strategy optimization
- performance optimization
- code simplification
- monitoring schema refinement
- scheduler / batching 微調

### Phase 2 前提
只有在以下條件成立時，才允許進行：
1. pipeline 已可跑
2. pytest / smoke tests 已存在
3. schema compatibility 已有驗證
4. dispatch / monitor / failure handling 已落地
5. 變更能被測試保護

---

## Phase 2 優化規則

即使進入 Phase 2，也仍然必須遵守：

- 不可破壞既有 schema
- 不可破壞既有 downstream
- 不可把 `prompt_pipeline/` 與 `pipeline/` 混在一起
- 只允許「可測試、可回滾、可比較」的優化
- 若效能優化與穩定性衝突，優先保守穩定

---

# 🧠 最小改動原則（但不是最小能力）

優先順序：

1. ✅ 新增 `pipeline/` 模組
2. ✅ 包裝既有函式
3. ✅ 將深度整合能力放在 orchestration 外層
4. ✅ 用 config / wrapper / dispatcher / monitor 補能力
5. ❌ 不要直接改爛舊 extraction
6. ❌ 不要亂搬檔案
7. ❌ 不要大改 import tree

注意：

> 最小改動 ≠ 最小功能。  
> 這次要的是「低侵入但高整合」的版本。

---

# 🚫 明確禁止的錯誤

❌ 把 prompt 邏輯寫進 `pipeline`  
❌ 重寫 extraction engine  
❌ 為了新架構改掉舊 entry point  
❌ 建立第二套 schema  
❌ 建立 `agent/`  
❌ 忽略測試  
❌ 使用真實 API 當測試  
❌ 在沒有測試保護的情況下進行大規模優化  
❌ 只做線性 for-loop 串接卻宣稱有 dispatcher  
❌ 只有 logger print，沒有結構化 stage/run metadata  
❌ 沒有 best-effort / fail-fast 切換  
❌ 多工後結果順序不穩或不可驗證  
❌ 用大量破壞性重構來換取表面上的「整潔」

---

# 🧪 實作順序（必須照做）

## Phase 1
1. repo 掃描與 reuse 分析
2. integration gap 分析（列出目前缺的深度整合能力）
3. `PipelineContext`
4. `pipeline_types`
5. `pipeline_config` / YAML loader
6. `pipeline_registry`
7. `pipeline_monitor`
8. `pipeline_dispatcher`
9. `pipeline_controller`
10. `chunk_summary`
11. `doc_type_classification`
12. extraction wrapper
13. merge strategies
14. `merge_multidim`
15. pipeline 註冊與跑通
16. mock LLM
17. pytest 最小測試
18. smoke demo
19. 將既有 entry point 最小接入新 pipeline

## Phase 2（只有在 Phase 1 完成後）
20. selective optimization
21. overlay refinement
22. merge quality improvement
23. chunk scheduling / batching tuning
24. monitoring refinement
25. optional clean refactor under test protection

---

# 📤 最後輸出必須包含

1. 新增檔案清單
2. 修改檔案清單
3. repo 掃描結果
4. integration gap 分析
5. reuse / wrapper 說明
6. deep integration 設計說明（dispatch / concurrency / monitoring / failure model）
7. pipeline 如何執行
8. 測試如何執行
9. smoke demo 如何執行
10. config 如何調整（例如 max_workers / fail_fast / retries）
11. TODO 清單
12. 若進入 Phase 2，列出哪些優化已做、哪些故意沒做

---

# 🧠 最重要的行為原則

當你不確定時，選擇：

- 最小改動
- 最大相容
- 可測試
- 可回滾
- 可觀測
- 可控併發
- 可部分失敗

---

# FINAL RULE

你不是在重寫這個系統。

你是在：

> 先幫既有系統加上一個可測試、可回滾、可觀測、可控多工、可深度整合的 pipeline 大腦  
> 並且把原本被簡化掉的派工、監控、平行處理、錯誤恢復能力補回來  
> 同時維持既有 execution layer 與 downstream schema 的相容性

如果你遇到取捨，優先順序是：

1. schema / downstream 相容
2. orchestration 深度整合落地
3. 測試可驗證
4. 低侵入
5. 效能優化
