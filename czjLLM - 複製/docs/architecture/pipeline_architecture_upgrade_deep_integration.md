# Pipeline Architecture Upgrade (Deep Integration)

## 目標

把目前的 task-setting + 平行化分析框架，升級成：

> 可組合、可測試、且深度整合既有運行骨幹的多階段 Pipeline 架構

同時保持：

- 既有 prompt / LLM execution layer
- 既有固定 JSON schema
- 既有 ES / DB / handlers downstream 相容性

## 關鍵補強

舊版參考檔偏向「新增一個 pipeline scaffold」。
這版明確要求：

- pipeline 要接上既有 dispatcher / task runner
- chunk stages 要優先重用既有平行執行機制
- stage trace / debug 要能接上 monitoring / logging
- 最終輸出要沿用既有 downstream 寫出路徑

## 層次

- `prompt_pipeline/`: prompt + LLM execution
- `pipeline/`: orchestration + context + merge strategy
- existing runtime: parallelism + dispatch + monitoring + downstream

## 第一條 pipeline

```text
全文
→ Existing Chunking / Parallel Path
→ Chunk Summary
→ DocType Classification
→ Type-aware Extraction
→ Type-aware Merger
→ 固定 JSON 輸出
```

## 實作要求

### PipelineContext
至少含：
- raw_text
- article_title
- article_date_iso
- chunks
- chunk_summaries
- doc_type_result
- extraction_results
- merged_result
- metadata

### StageResult
```python
{
  "stage_name": ...,
  "success": ...,
  "data": ...,
  "debug": ...,
  "errors": ...
}
```

### PipelineOutput
```python
{
  "output_type": ...,
  "task_name": ...,
  "success": ...,
  "data": ...,
  "metadata": ...,
  "errors": ...
}
```

## 驗收

- pipeline 可 end-to-end 跑完
- pipeline 可進既有 dispatcher 或主執行路徑
- chunk stage 可接既有 parallel runtime
- monitoring / downstream compatibility 保留
- 舊 extraction 路徑仍可跑
- schema 不破
