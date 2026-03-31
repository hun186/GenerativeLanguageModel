# AGENTS.md

## 🎯 Goal

Refactor this repository into a:

> **Composable Multi-Stage LLM Pipeline System**

While STRICTLY:

* preserving existing behavior
* preserving output schema
* NOT breaking prompt_pipeline execution layer
* using minimal invasive changes

---

## 🚨 Critical Constraints (MUST FOLLOW)

### 1. DO NOT break existing system

* Existing extraction must still work
* Existing JSON schema must NOT change
* Existing prompt_pipeline must remain intact

---

### 2. DO NOT move LLM logic into pipeline/

LLM-related code MUST stay in:

prompt_pipeline/

pipeline/ is ONLY for:

* orchestration
* context passing
* stage coordination

---

### 3. Prefer ADDITION over MODIFY

Good:

* wrap existing functions
* add new modules
* extend behavior

Bad:

* rewrite core logic
* delete old code

---

### 4. Pipeline is OUTER LAYER

Correct structure:

pipeline/
→ controls flow

prompt_pipeline/
→ executes LLM

---

### 5. All stages must be independently testable

Each step must:

* accept input
* return structured result
* not depend on hidden global state

---

## 🧱 Architecture Rules

### Layer Separation

| Layer           | Responsibility         |
| --------------- | ---------------------- |
| prompt_pipeline | prompt + LLM execution |
| pipeline        | workflow orchestration |

---

### PipelineContext is REQUIRED

All stages must read/write via:

PipelineContext

---

### Output MUST be wrapped

Final output MUST follow:

PipelineOutput format

BUT:

* `data` MUST preserve original format
* DO NOT change existing JSON schema

---

## ⚙️ Implementation Strategy

### Step Order (STRICT)

1. PipelineContext
2. pipeline_controller
3. chunk_summary
4. doc_type_classification
5. prompt overlay
6. extraction wrapper
7. merge strategy
8. full pipeline

DO NOT skip steps.

---

## ❌ Forbidden

* ❌ rewriting prompt_pipeline
* ❌ duplicating extraction logic
* ❌ creating multiple incompatible schemas
* ❌ mixing orchestration into LLM layer

---

## ✅ Success Criteria

* pipeline runs end-to-end
* doc_type affects extraction
* merger changes behavior
* old system still works
* output schema unchanged

---

## 🧠 Mental Model

Think:

> "Add a brain on top, not replace the body"

---

## 📌 Final Rule

When unsure:

> KEEP OLD SYSTEM WORKING FIRST
