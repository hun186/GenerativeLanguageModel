# Pipeline Skeleton Guide

## Purpose

This document defines the **minimal pipeline scaffold** for this repository.

It is intended for:

* Codex (implementation guidance)
* Developers (structure reference)

---

# 🧱 Pipeline Structure

```text
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

  merge/
    base_strategy.py
    merge_selector.py
    *.py
```

---

# 🧠 Design Rules

## 1. Pipeline is orchestration only

pipeline/ MUST NOT:

* call LLM directly
* contain prompt logic
* duplicate extraction logic

---

## 2. LLM execution stays here

```text
prompt_pipeline/
```

Responsible for:

* prompt construction
* LLM calls
* retries
* parsing

---

## 3. Steps are thin wrappers

Each step should:

* read from PipelineContext
* call existing logic (via prompt_pipeline)
* write back to PipelineContext

---

## 4. No logic duplication

DO:

* wrap existing extraction

DO NOT:

* rewrite extraction logic

---

## 5. Merge is strategy-based

```text
merge/
  base_strategy.py
  *_strategy.py
```

* selected via doc_type
* applied at document level

---

# ⚙️ Execution Flow

```text
Input
→ chunk_text()
→ chunk_summary
→ doc_type_classification
→ extraction_multidim
→ merge_multidim
→ Output
```

---

# 📦 Output Rule

Pipeline MUST return:

```python
{
  output_type,
  task_name,
  success,
  data,
  metadata,
  errors
}
```

BUT:

* `data` must preserve original format
* no schema breaking

---

# 🚨 Common Mistakes (MUST AVOID)

❌ Moving LLM logic into pipeline/
❌ Rewriting extraction logic
❌ Mixing prompt and orchestration layers
❌ Creating multiple output schemas

---

# 🎯 Goal

> Provide a minimal, stable scaffold that can evolve into a full pipeline system
