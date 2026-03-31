# Architecture Overview

## System Evolution

This project evolves from:

> **Single-stage LLM task execution**

into:

> **Composable Multi-Stage LLM Pipeline System**

---

# 🧠 Core Idea

From:

```
Task → LLM → Output
```

To:

```
Input
→ Multi-Stage Pipeline
→ Output (format depends on task)
```

---

# 🧱 Architecture (Critical)

## Two-Layer Design (VERY IMPORTANT)

### Layer 1 — `prompt_pipeline/`

Responsible for:

* prompt construction
* LLM calls
* retry / fallback
* result parsing

👉 This layer already exists and MUST NOT be rewritten

---

### Layer 2 — `pipeline/`

Responsible for:

* workflow orchestration
* stage sequencing
* context passing
* merge strategies
* pipeline configuration

👉 This is the NEW layer added on top

---

## 🔥 Key Rule

> pipeline orchestrates
> prompt_pipeline executes

---

# 🔩 Key Concepts

## 1. Stage (Node)

A reusable processing unit.

Examples:

* chunk_summary
* doc_type_classification
* extraction_multidim
* merge_multidim

---

## 2. Pipeline

An ordered sequence of stages.

Example:

```
chunk_summary
→ doc_type_classification
→ extraction_multidim
→ merge_multidim
```

---

## 3. Pipeline Controller

Responsible for:

* executing pipeline
* passing context
* handling stage order
* managing chunk vs document level

---

## 4. PipelineContext

Shared object passed across stages.

Stores:

* raw_text
* chunks
* doc_type_result
* extraction_results
* merged_result

---

# 🧱 Execution Model

## Chunk-Level Stages

* run per chunk
* parallelizable

Examples:

* chunk_summary
* extraction

---

## Document-Level Stages

* run once per document

Examples:

* doc_type_classification
* merge

---

# 📦 Pipeline Output Interface

All pipelines return a unified structure:

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

---

## Important

* `data` preserves original output format
* NOT all pipelines return JSON
* system must support multiple output types

---

# 🧪 First Pipeline

## doc_type_aware_extraction

```
Raw Text
→ Chunking
→ Chunk Summary
→ DocType Classification
→ Type-aware Extraction
→ Type-aware Merger
→ Output
```

---

# 🧠 Why DocType Matters

Different document types require different strategies:

| Type      | Behavior            |
| --------- | ------------------- |
| event     | single event focus  |
| interview | Q&A + statements    |
| profile   | career narrative    |
| issue     | trend / problem     |
| report    | structured findings |
| legal     | rules / agreements  |

---

# 🔄 Prompt Architecture

Move from:

```
One giant prompt
```

To:

```
Base Prompt
+ Type Overlay
```

👉 Implemented inside `prompt_pipeline/`

---

# 🔀 Merge Strategy

Different doc_types use different merging logic.

Examples:

* Event → select core event
* Interview → preserve conversation
* Profile → avoid fake timeline
* Issue → avoid forced event
* Report → reduce noise
* Legal → keep structure minimal

---

# 🔮 Future Extensions

This architecture supports:

## Translation Pipeline

```
Language Detection → Translation → Summary
```

## Knowledge Preparation

```
Chunk Summary → Global Summary → Entity Extraction
```

## Retrieval Optimization

```
Extraction → Canonicalization → Index Formatting
```

---

# ⚠️ Design Constraints

## MUST KEEP

* existing JSON schema (for extraction)
* agent compatibility
* ES compatibility
* prompt_pipeline intact

---

## MUST NOT

* rewrite prompt_pipeline
* introduce multiple incompatible schemas
* mix orchestration into LLM layer

---

# 📍 Full Specification

Detailed implementation:

👉 `docs/architecture/pipeline_architecture_upgrade.md`

---

# 🧾 Summary

This is not a rewrite.

This is:

> **An orchestration layer added on top of an existing LLM system**

---

## Final Principle

> Add a brain, not replace the body
