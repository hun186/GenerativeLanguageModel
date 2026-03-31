# Codex 實作版：將現有 task-setting / 平行化分析系統升級為可組合多階段 LLM Pipeline（正式整合版）

## 0. 文件目的

這份文件是給 Codex 直接參考與實作的工程規格。

目標不是重寫整個專案，而是：

1. **保留既有 task setting + 平行化分析主體**
2. **保留既有 LLM 呼叫與文字處理流程**
3. **保留既有固定 JSON 輸出 schema（對於結構化抽取任務）**
4. **新增可重用的多階段 pipeline 能力**
5. **先落地第一個具體案例：文件級 doc_type 分類 → type-aware 抽取 → merger 收斂**
6. **讓未來可以擴充 translation / summary / canonicalization 等節點**

---

# 1. 現況與核心問題

## 1.1 現況架構

目前系統大致是：

```text
選定 task setting
→ 輸入文本
→ LLM 執行
→ 得到輸出
```

其中輸出可能是：

- 原始文字字串
- 固定 JSON 結果
- 後續寫入 txt / DB / ES 的資料

長文情況下：

```text
全文
→ 切塊
→ 各 chunk 平行跑同一任務
→ 將 chunk 結果整併為單一最終結果
```

---

## 1.2 問題來源

目前的抽取系統幾乎把所有文本都當成同一種事件抽取任務處理。

但實務上，輸入文本可能是：

- 標準事件新聞（event）
- 專訪（interview）
- 人物專題 / 生涯回顧（profile）
- 社會議題 / 趨勢報導（issue）
- 報告 / 監測 / 研究彙編（report）
- 條約 / 法規 / 規約 / 制度性文件（legal）

若沒有先做文件級判型，後果是：

- profile / issue / report / legal 會被硬壓成單一 event
- `Event.subject / action / object` 容易語義漂移
- `Event_Timeline` 會混入大量背景歷史、圖片圖說、制度沿革
- `Impact` 會被寫成整篇評論，而非主事件後果
- 切塊後局部 chunk 更容易誤判

---

## 1.3 不能直接改成多套 schema 的原因

後續代理工具與 ES 查詢依賴固定欄位，例如：

- `multidim_event_json.Event.subject`
- `multidim_event_json.Event.object`
- `multidim_event_json.Event.location`
- `multidim_event_json.Event_Timeline.description`
- `multidim_event_json.Person.name`
- `multidim_event_json.Involved_Parties.party_name`
- `multidim_event_json.evidence_snippets.text`

因此不能直接改成：

- event 用 `Event.*`
- report 用 `Report.*`
- profile 用 `Profile.*`

這會直接破壞既有檢索與代理工具。

**正確方向是：固定輸出外殼不變，文類感知只影響填值策略與整併策略。**

---

# 2. 本次改造總目標

## 2.1 目標一句話

把目前的單任務 LLM 系統，升級為：

> **可組合的多階段 Pipeline 架構，但保持既有 schema、既有工作流程與既有 downstream 相容性。**

---

## 2.2 系統升級目標

將：

```text
Task → LLM → Output
```

升級為：

```text
Input
→ 多階段 Pipeline
→ Output（型態依任務而定）
```

---

## 補充說明

目前系統中，「結構化 JSON 輸出」只是其中一種任務（例如 multidimensional extraction）。

未來 pipeline 應支援多種輸出型態，例如：

- 結構化 JSON（資訊抽取）
- 純文字（翻譯）
- 摘要文本（summary）
- Markdown 報告
- 表格 / SQL-ready 結構
- embedding / 向量資料（未來）

因此：

> Pipeline 架構的設計應聚焦於「多階段處理能力」，而不是限制輸出格式。

---

## 2.3 本次優先落地案例

先完成這個 pipeline：

```text
全文
→ Chunk Summary（可選）
→ DocType Classification（文件級）
→ Type-aware Extraction（chunk 級）
→ Type-aware Merger（文件級）
→ 固定 JSON 輸出
```

這個案例是第一個真正的「二階段分析」：

### 第 1 階段：文件級分類
先判定整篇屬於哪一類：

- event
- interview
- profile
- issue
- report
- legal
- mixed

### 第 2 階段：真正抽取
仍然用現有固定 JSON 結構抽取，但根據 `doc_type` 調整：

- prompt overlay
- chunk extraction guidance
- merger 收斂規則

---

# 3. 目標架構

## 3.1 新架構概念

將 task setting 升級成可組合節點（node），由 pipeline controller 決定串接順序。

```text
Input
→ Node A
→ Node B
→ Node C
→ Output
```

---

## 3.2 三個核心概念

### Node
一個可重用的分析節點，例如：

- Language Detection
- Translation
- Chunk Summary
- DocType Classification
- Info Extraction
- Merger

### Pipeline
多個節點的有序組合，例如：

- `doc_type_aware_extraction`
- `translate_then_summarize`

### Controller / Orchestration Layer
負責：

- 執行 pipeline
- 在節點間傳遞資料
- 管理 chunk-level / document-level 節點
- 管理條件式 routing

---

# 4. 實作分層原則（雙層架構）

本專案採雙層架構：

## Layer 1 — `prompt_pipeline/`
既有 execution layer，負責：

- prompt 組裝
- LLM 呼叫
- retry
- result handling
- 單次任務 prompt flow

這一層 **不應被重寫**，而應被重用。

---

## Layer 2 — `pipeline/`
新增 workflow layer，負責：

- 多階段 workflow orchestration
- PipelineContext 傳遞
- steps 執行順序
- chunk / document level 控制
- merger strategy 選擇
- pipeline config / pipeline registration

---

## 職責切分（非常重要）

| 類型 | 放哪裡 |
|------|--------|
| prompt / LLM execution | `prompt_pipeline/` |
| workflow orchestration | `pipeline/` |
| stage / step 邏輯 | `pipeline/steps/` |
| merge strategy | `pipeline/merge/` |
| prompt assets | `prompt_pipeline/prompts/` |

---

# 5. 建議的新模組與檔案結構

以下是建議結構，不要求完全一致，但 Codex 應建立清楚分層，並對齊現有 repo 命名風格。

```text
czjLLM/

  prompt_pipeline/
    clients.py
    llm_caller.py
    prompt_generator.py
    result_handler.py
    pipeline_controller.py

    prompts/
      base/
        multidim_base_prompt.py
      overlays/
        doc_type_event.py
        doc_type_interview.py
        doc_type_profile.py
        doc_type_issue.py
        doc_type_report.py
        doc_type_legal.py
        doc_type_mixed.py

  pipeline/
    pipeline_context.py
    pipeline_types.py
    pipeline_config.py
    pipeline_utils.py
    pipeline_controller.py

    steps/
      chunk_summary.py
      doc_type_classification.py
      extraction_multidim.py
      merge_multidim.py
      translation.py
      summarization.py

    merge/
      base_strategy.py
      merge_selector.py
      event_strategy.py
      interview_strategy.py
      profile_strategy.py
      issue_strategy.py
      report_strategy.py
      legal_strategy.py
      mixed_strategy.py
```

如果目前專案結構不便大調整，至少也要做到：

- pipeline orchestration 抽出成單獨模組
- doc type classification 抽出成單獨 step
- prompt overlay 抽出成單獨模組
- merger strategy 抽出成單獨模組
- prompt / LLM execution 邏輯保留在 `prompt_pipeline/`

---

# 6. 需要新增的資料結構

## 6.1 Pipeline Context

建立一個在 pipeline 中傳遞的 context 物件。

### 建議資料結構

```python
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

@dataclass
class PipelineContext:
    raw_text: str
    article_title: Optional[str] = None
    article_date_iso: Optional[str] = None
    chunks: List[str] = field(default_factory=list)
    chunk_summaries: List[Dict[str, Any]] = field(default_factory=list)
    doc_type_result: Optional[Dict[str, Any]] = None
    extraction_results: List[Dict[str, Any]] = field(default_factory=list)
    merged_result: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
```

---

## 6.2 Doc Type Result

```python
DocTypeResult = {
    "doc_type": "event | interview | profile | issue | report | legal | mixed",
    "doc_type_confidence": 0.87,
    "secondary_type": None,
    "has_primary_event": True,
    "routing_reason": "本文以專訪為主，但有明確採訪當下鉤子"
}
```

---

## 6.3 Stage Output 規格

每個 step 應至少回傳：

```python
{
  "stage_name": "doc_type_classification",
  "success": True,
  "data": {...},
  "debug": {...},
  "errors": []
}
```

這能讓 pipeline controller 更穩定，也方便 debug。

---

## 6.4 Pipeline Output Interface 定義（相容版）

Pipeline 架構必須支援多種輸出型態，不可將最終輸出限制為固定 JSON。

因此，pipeline 的輸出介面應採用：

- **外層統一**
- **內層內容可依任務變化**

也就是說：

- pipeline / step 的回傳外殼格式應一致
- `data` 內容型態可依任務不同而改變

### 建議統一格式

```python
PipelineOutput = {
    "output_type": "json | text | markdown | table | sql_rows | embeddings | other",
    "task_name": "doc_type_aware_extraction",
    "success": True,
    "data": ...,
    "metadata": {...},
    "errors": []
}
```

---

### 欄位說明

#### `output_type`
表示最終輸出資料型態，例如：

- `json`：結構化資訊抽取
- `text`：純文字輸出
- `markdown`：摘要 / 報告 / 條列整理
- `table`：表格型資料
- `sql_rows`：可直接入 SQL / ETL 的列資料
- `embeddings`：向量化結果
- `other`：其他特殊型態

#### `task_name`
標示此輸出所屬任務或 pipeline 名稱。

#### `success`
表示 pipeline 是否成功完成。

#### `data`
真正的任務輸出內容。  
這個欄位不應被限制為固定 JSON 結構，而應依任務需求變化。  
它可以是：

- `str`
- `dict`
- `list`
- 任何既有任務原本已使用的輸出型態

#### `metadata`
附加資訊，例如：

- schema version
- doc_type
- execution trace
- stage debug info
- token / latency / model info
- article_title / source metadata

#### `errors`
錯誤訊息列表。若成功則為空陣列。

---

### 範例 1：結構化抽取

```python
{
    "output_type": "json",
    "task_name": "doc_type_aware_extraction",
    "success": True,
    "data": {
        "multidim_event_json": {...}
    },
    "metadata": {
        "doc_type": "event",
        "doc_type_confidence": 0.91
    },
    "errors": []
}
```

---

### 範例 2：翻譯任務

```python
{
    "output_type": "text",
    "task_name": "translation",
    "success": True,
    "data": "這是一段翻譯後的文本。",
    "metadata": {
        "source_language": "en",
        "target_language": "zh-TW"
    },
    "errors": []
}
```

---

### 範例 3：摘要任務

```python
{
    "output_type": "markdown",
    "task_name": "summarization",
    "success": True,
    "data": "## 摘要\n\n- 重點一\n- 重點二",
    "metadata": {
        "summary_style": "bullet"
    },
    "errors": []
}
```

---

### 與既有系統的相容方式

原本：

```python
result = call_llm(...)
save_txt(result)
write_db(result)
```

現在：

```python
output = run_pipeline(...)
result = output["data"]
save_txt(result)
write_db(result)
```

也就是：

- 舊的字串處理邏輯幾乎不動
- 只是外面多了一層 wrapper

---

### 設計原則

1. **外層介面統一，內層資料型態彈性**
2. **不可假設所有 pipeline 最終都輸出 JSON**
3. **目前的 fixed-schema JSON extraction 只是其中一種 pipeline**
4. **未來 translation / summary / table / embedding pipeline 都應沿用同一外層介面**
5. **若某些舊任務已有既有輸出格式，可在 wrapper 層外掛此介面，不必立即重寫舊邏輯**

---

### 與 Stage Output 的關係

- `Stage Output`：描述單一 step 執行結果
- `Pipeline Output Interface`：描述整條 pipeline 的最終輸出格式

兩者不可混用。

也就是：

- step 間傳遞可使用 `StageResult`
- pipeline 對外回傳應使用 `PipelineOutput`

---

# 7. 第一個要落地的 Pipeline：doc_type_aware_extraction

## 7.1 Pipeline 定義

```yaml
pipeline_name: doc_type_aware_extraction
steps:
  - chunk_summary
  - doc_type_classification
  - extraction_multidim
  - merge_multidim
```

---

## 7.2 各 step 職責

### Step 1: chunk_summary
用途：

- 產生文件級判型可用的全文骨架資訊
- 不要求很長，只要讓分類器能看出整體文類

### Step 2: doc_type_classification
用途：

- 對整篇文本做文類判定
- 這一步一定是 document-level，不可讓 chunk 各自決定最終類型

### Step 3: extraction_multidim
用途：

- 繼續使用現有固定 JSON schema 抽取
- 但每個 chunk 都要收到 doc_type 與 document-level guidance

### Step 4: merge_multidim
用途：

- 根據 doc_type 決定合併策略
- 不能只是簡單欄位拼接與去重

---

# 8. DocType Classification 的實作規格

## 8.1 任務設定檔新增

新增 task setting，例如：

```python
"DocType-Classification": {
    "CT_name": "文件類型判定",
    "InputCutLen": 400,
    "template": ...
}
```

---

## 8.2 輸入內容建議

分類器不應直接吃原始全文完整內容（成本高、雜訊多），而應優先吃「全文骨架」：

- article title
- 前幾段
- 後幾段
- chunk summaries

### 可行做法

建立一個 helper：

```python
def build_doctype_input(
    article_title: str,
    raw_text: str,
    chunk_summaries: list[dict],
    head_paragraphs: int = 3,
    tail_paragraphs: int = 2,
) -> str:
    ...
```

輸出一段供分類器使用的壓縮文本。

---

## 8.3 分類器輸出格式

必須固定、可機器解析：

```json
{
  "doc_type": "interview",
  "doc_type_confidence": 0.88,
  "secondary_type": "event",
  "has_primary_event": true,
  "routing_reason": "本文以專訪為主，內容包含大量回顧與立場說明，但有明確採訪當下鉤子。"
}
```

---

## 8.4 類型定義

### event
- 有明確主事件
- 可回答「發生了什麼」
- 有單一主體動作

### interview
- 以訪談、對話、回應、說明為主
- 有受訪者
- 有當下鉤子，但背景很多

### profile
- 人物生涯、人物專題、回顧型報導
- 沒有單一事件核心

### issue
- 描述社會問題、趨勢、結構現象
- 有多個案例與觀點
- 無單一事件主幹

### report
- 監測報告、研究報告、數據匯總

### legal
- 條約、法案、規約、制度性文本

### mixed
- 無法穩定單一歸類

---

# 9. Extraction Stage 的實作規格

## 9.1 不改既有固定輸出 schema

這是最高優先。

既有：

- `multidim_event_json`
- `Event.subject`
- `Event.object`
- `Event.action`
- `Event_Timeline`
- `Person`
- `Involved_Parties`
- `Impact`
- `evidence_snippets`

全部保留。

---

## 9.2 抽取 prompt 改造方式

### 不要做的事

- 不要複製 6 份完整大 prompt
- 不要每類一整份獨立 task setting
- 不要把 prompt / LLM execution 邏輯重寫到 `pipeline/`

### 應做的事

改成：

- `BASE_PROMPT`
- `TYPE_OVERLAY_MAP`

例如：

```python
TYPE_OVERLAY_MAP = {
    "event": EVENT_OVERLAY,
    "interview": INTERVIEW_OVERLAY,
    "profile": PROFILE_OVERLAY,
    "issue": ISSUE_OVERLAY,
    "report": REPORT_OVERLAY,
    "legal": LEGAL_OVERLAY,
    "mixed": MIXED_OVERLAY,
}
```

### prompt builder

```python
def build_multidim_prompt(
    content: str,
    base_prompt: str,
    doc_type: str,
    doc_type_confidence: float | None = None,
    has_primary_event: bool | None = None,
    routing_reason: str | None = None,
    article_title: str | None = None,
) -> str:
    overlay = TYPE_OVERLAY_MAP.get(doc_type, TYPE_OVERLAY_MAP["mixed"])
    return (
        base_prompt
        + "\n\n【文件類型判定結果】\n"
        + f"- doc_type: {doc_type}\n"
        + f"- doc_type_confidence: {doc_type_confidence}\n"
        + f"- has_primary_event: {has_primary_event}\n"
        + (f"- routing_reason: {routing_reason}\n" if routing_reason else "")
        + "\n【對應抽取策略】\n"
        + overlay
        + "\n\n☆下列為輸入任務文本：\n"
        + content
    )
```

---

## 9.3 每個 chunk 都要帶 document-level context

這很重要。

長文切塊後，每個 chunk prompt 應帶：

- doc_type
- confidence
- has_primary_event
- routing_reason
- article_title（若有）

否則 chunk 很容易局部誤判。

---

## 9.4 建議新增中間態欄位（只供 merger 使用，可不入最終索引）

如果你願意，chunk 級 extraction 可回傳額外 metadata：

```json
{
  "_chunk_meta": {
    "chunk_index": 2,
    "chunk_role": "background | main_event | issue_case | profile_context | policy_context | quote_block",
    "chunk_confidence": 0.72
  }
}
```

若不想污染最終輸出，可在 merger 前移除。

---

# 10. Type Overlay 內容要求

Codex 需要新增這些 overlay 字串常數或檔案。

## 10.1 event overlay

重點：

- 優先抓單一主事件
- Event.subject / action / object 要保持標準事件結構
- Event_Timeline 只放主事件直接節點
- 不要把歷史背景大段塞入 timeline

---

## 10.2 interview overlay

重點：

- Event 主語義優先抽成：受訪 / 說明 / 回應 / 受訪談話
- 若內容大量回顧背景，背景僅作支撐，不得吞掉主事件
- Impact 以知識傳遞、立場說明、政策訊號為主
- Event_Timeline 不可變成人生履歷

---

## 10.3 profile overlay

重點：

- Event.subject = 人物
- Event.action = 回顧職涯 / 講述經歷 / 接受專訪
- Event.object = 生涯、工作、貢獻
- timeline 可保留少量生涯節點，但不得假裝是單一事件流程
- impact 一律保守

---

## 10.4 issue overlay

重點：

- Event.subject 應優先填議題名稱
- Event.action 可為：上升 / 惡化 / 引發警告 / 推動討論 / 持續存在
- object = 受影響群體或對象
- timeline 只留關鍵案例或政策節點
- 不得強造單一事件後果

---

## 10.5 report overlay

重點：

- Event.subject = 報告名稱或發布機構
- Event.action = 發布 / 評估 / 指出 / 彙整 / 監測
- Event.object = 報告主題
- timeline 僅留報告發布與極少量關鍵背景節點
- involved parties 要強力去噪

---

## 10.6 legal overlay

重點：

- Event.subject = 條約 / 法規 / 規約名稱或使其通過之主體
- Event.action = 通過 / 生效 / 規定 / 建立 / 裁定
- Event.object = 文件名稱或制度對象
- timeline 僅留制度節點
- 不得把條文角色與制度元素全部塞進 parties

---

## 10.7 mixed overlay

重點：

- 若無法形成穩定 event，允許使用較高層摘要式填法
- timeline / impact / parties 一律保守
- 優先避免錯配與 hallucination

---

# 11. Merger 的實作規格

## 11.1 現況問題

目前長文平行化系統的 merger 若只是：

- 欄位拼接
- 重複去除
- 信心排序

那在 doc_type-aware 情境下仍然不夠。

原因：

- event 類需要選單一主事件
- interview 類要保留採訪主幹
- profile 類不能讓生涯 timeline 吞掉一切
- issue 類不能假拼單一事件

---

## 11.2 建議實作方式

建立 strategy pattern：

```python
class BaseMergeStrategy:
    def merge(self, extraction_results, context):
        raise NotImplementedError
```

再實作：

- `EventMergeStrategy`
- `InterviewMergeStrategy`
- `ProfileMergeStrategy`
- `IssueMergeStrategy`
- `ReportMergeStrategy`
- `LegalMergeStrategy`
- `MixedMergeStrategy`

### strategy dispatcher

```python
def get_merge_strategy(doc_type: str) -> BaseMergeStrategy:
    ...
```

---

## 11.3 各類 strategy 基本行為

### EventMergeStrategy
- 選最穩定的單一主事件
- 合併最強 evidence
- timeline 只保留主事件節點
- impact 聚焦已發生後果

### InterviewMergeStrategy
- 主事件定義為受訪 / 說明 / 回應
- 背景時間線限縮
- 不可讓履歷化內容蓋掉主事件

### ProfileMergeStrategy
- 主體是人物
- timeline 視為 career milestones
- impact 一律保守
- 不可輸出像突發事件的語義

### IssueMergeStrategy
- 不硬拼假事件
- subject 改為議題名稱
- action 改為趨勢或警告類動作
- timeline 僅保留關鍵案例與政策節點

### ReportMergeStrategy
- 主體為報告 / 發布機構
- 去除報告中歷史百科與實體 dump
- 只保留高價值 findings support

### LegalMergeStrategy
- 主體為法規 / 條約 / 制度文本
- timeline 僅保留制度節點
- parties 嚴格去噪

### MixedMergeStrategy
- 採保守融合
- 優先避免矛盾與錯配

---

## 11.4 merger 輸出

對於 `doc_type_aware_extraction` 這類結構化抽取 pipeline：

- 最終輸出仍然是既有固定 JSON schema
- 不得改 schema
- 可在 pipeline 外層以 `PipelineOutput` 包裝
- `data` 內部仍維持既有 schema 內容

例如：

```python
{
    "output_type": "json",
    "task_name": "doc_type_aware_extraction",
    "success": True,
    "data": {
        "multidim_event_json": {...}
    },
    "metadata": {
        "doc_type": "event"
    },
    "errors": []
}
```

---

# 12. Pipeline Controller 的實作規格

## 12.1 不重寫平行化核心，只加 orchestration

重點：

- 不要推翻原本平行處理框架
- 只在外層增加多階段能力
- 不要把 `prompt_pipeline/` 既有 LLM execution 重寫到 `pipeline/`

---

## 12.2 建議新增 pipeline controller

對齊 repo 命名風格，建議使用：

```python
run_pipeline(pipeline_name: str, raw_text: str, metadata: dict | None = None)
```

而不是強制引入過重的 framework abstraction。

---

## 12.3 執行流程（doc_type_aware_extraction）

```python
def run_doc_type_aware_extraction(raw_text: str, metadata: dict | None = None):
    ctx = PipelineContext(raw_text=raw_text, metadata=metadata or {})

    # Step 1: chunk
    ctx.chunks = chunk_text(raw_text)

    # Step 2: chunk summaries
    ctx.chunk_summaries = run_chunk_summaries(ctx.chunks, metadata=ctx.metadata)

    # Step 3: document-level classification
    doctype_input = build_doctype_input(
        article_title=ctx.metadata.get("article_title", ""),
        raw_text=raw_text,
        chunk_summaries=ctx.chunk_summaries,
    )
    ctx.doc_type_result = run_doc_type_classification(doctype_input)

    # Step 4: type-aware extraction on chunks
    ctx.extraction_results = run_chunk_extraction(
        chunks=ctx.chunks,
        doc_type_result=ctx.doc_type_result,
        metadata=ctx.metadata,
    )

    # Step 5: merge
    ctx.merged_result = merge_extraction_results(
        extraction_results=ctx.extraction_results,
        doc_type_result=ctx.doc_type_result,
        metadata=ctx.metadata,
    )

    return {
        "output_type": "json",
        "task_name": "doc_type_aware_extraction",
        "success": True,
        "data": ctx.merged_result,
        "metadata": {
            "doc_type": ctx.doc_type_result.get("doc_type") if ctx.doc_type_result else None,
            "doc_type_confidence": ctx.doc_type_result.get("doc_type_confidence") if ctx.doc_type_result else None,
        },
        "errors": []
    }
```

---

## 12.4 支援未來其他 pipeline

未來 pipeline controller 也要能跑：

### translate_then_summarize

```text
Language Detection → Translation → Summary
```

### translate_then_extract

```text
Language Detection → Translation → DocType Classification → Extraction → Merger
```

### knowledge_prep

```text
Chunk Summary → Global Summary → Entity Extraction → Index Formatter
```

因此 pipeline 應可配置，不應寫死在單一函式內。

---

# 13. Pipeline Config

## 13.1 建議建立 pipeline config

```python
PIPELINE_CONFIG = {
    "doc_type_aware_extraction": [...],
    "translate_then_summarize": [...],
}
```

或改用 YAML / JSON config。

---

## 13.2 建議 pipeline config 格式

```yaml
pipeline_name: doc_type_aware_extraction
steps:
  - name: chunk_summary
    level: chunk
  - name: doc_type_classification
    level: document
  - name: extraction_multidim
    level: chunk
  - name: merge_multidim
    level: document
```

未來再支援：

- conditional stage
- optional stage
- stage parameter injection

---

# 14. 兼容未來可組合能力

本次雖然先落地 doc_type-aware extraction，但架構要預留給以下能力：

## 14.1 翻譯 + 摘要

```text
Language Detection
→ Translation
→ Summary
```

## 14.2 翻譯 + 抽取

```text
Language Detection
→ Translation
→ DocType Classification
→ Extraction
→ Merger
```

## 14.3 檢索前知識準備

```text
Chunk Summary
→ Global Summary
→ Entity Extraction
→ Canonicalization
→ Index Formatter
```

Codex 在設計 node / controller / config 時，要考量這些未來用例，不要只針對 doc_type-aware extraction 寫死。

---

# 15. 與既有 ES / DB / agent 相容的要求

## 15.1 對結構化抽取任務，最終固定 JSON schema 不可破壞

最高優先要求：

- 不刪除現有主要欄位
- 不改既有欄位名稱
- 最終輸出仍可被現有 ES / agent 查詢使用

---

## 15.2 可新增 metadata，但要分清層級

可新增但不建議直接進現有主索引的欄位：

- `doc_type`
- `doc_type_confidence`
- `_chunk_meta`
- `_routing_reason`

若最終要入索引，請與主輸出區分好層級。

---

## 15.3 對純文字任務，需保持原有處理方式相容

例如：

- 存 txt
- 寫回資料庫
- 後處理原始生成文字

應可透過：

```python
result = output["data"]
```

方式直接取回原始內容，不強迫重寫舊 downstream。

---

# 16. 驗收標準

## 16.1 架構層
- 可以定義 pipeline
- 可以執行多 step
- 可以在 step 間傳遞 context
- chunk-level / document-level step 都可運作

## 16.2 doc_type-aware extraction 層
- 新增文件級分類 step
- extraction step 可注入 doc_type
- merger 會依 doc_type 切換策略

## 16.3 相容層
- 舊 extraction 任務仍可跑
- 舊 schema 不破
- 不影響既有 ES / DB / agent downstream
- 純文字任務仍可維持原有處理邏輯

## 16.4 品質層
對以下類型文本，抽取品質應比現在更穩：

- interview
- profile
- issue
- report
- legal

至少要減少：

- 背景歷史塞滿 timeline
- 專訪被硬抽成假事件
- issue 被硬拼成單一 event
- report / legal 的 parties 與 impact 爆量污染

---

# 17. Codex 實作優先順序

## Phase 1（必要）
1. 新增 `DocType-Classification` task setting
2. 建立 `PipelineContext`
3. 建立 pipeline controller 基礎框架
4. 將 extraction prompt 改為 `base + overlay`
5. 新增 merger strategy dispatcher
6. 完成 `doc_type_aware_extraction` pipeline

## Phase 2（建議）
1. 抽出 pipeline config / YAML config
2. 補齊 chunk-level 與 document-level step abstraction
3. 新增 debug / tracing 資訊
4. 將 output wrapper 標準化

## Phase 3（未來）
1. 增加 Translation node
2. 增加 Summary node
3. 增加 Canonicalization node
4. 增加可視化 pipeline tracing

---

# 18. 最後總結

本次重構不是要把系統改成很多套彼此不相容的 pipeline。

真正要做的是：

> **把目前的 task-setting + 平行化分析框架，升級成可組合的多階段 LLM pipeline，而第一個落地案例就是：文件級 doc_type 分類 → type-aware 抽取 → type-aware merger。**

對 Codex 來說，最重要的原則只有四個：

1. **保留既有固定 JSON schema（對結構化抽取任務）**
2. **不要破壞既有 ES / DB / agent 相容性**
3. **保留既有 prompt / LLM execution layer**
4. **用最小侵入方式，先把二階段分析做成第一個可重用 pipeline**

如果做對，這個架構之後就能自然擴充成：

- 翻譯 → 摘要
- 翻譯 → 抽取
- 長文知識準備
- retrieval-ready pre-processing
- multi-task composable analysis

---

# 最終一句話

> `prompt_pipeline/` 負責 LLM execution  
> `pipeline/` 負責 workflow orchestration  

兩者不能混。
