# Codex Execution Plan: Pipeline Upgrade (Repo-Aligned Version)

## 🎯 Goal

Upgrade system into:

> **Composable Multi-Stage LLM Pipeline**

While:

* preserving existing schema
* maintaining backward compatibility
* introducing doc_type-aware extraction

---

# 🧭 Execution Rules (IMPORTANT)

1. DO NOT break existing output schema
2. DO NOT remove existing extraction logic
3. Prefer wrapper / extension / overlay, not rewrite
4. Each task must be independently testable
5. Follow task order and dependencies strictly
6. Preserve backward compatibility at every step
7. Reuse existing `prompt_pipeline/` logic
8. Follow existing naming conventions in repo

---

# 🏗️ Architecture Rule (Two-Layer)

## Layer 1 — prompt_pipeline (existing)

Responsible for:

* prompt generation
* LLM calling
* retry
* result handling

## Layer 2 — pipeline (new)

Responsible for:

* workflow orchestration
* stage execution order
* context passing
* merge strategy selection

---

# ❌ DO NOT CREATE

* agent/
* stages/（use steps instead）
* registry/
* abstract framework-style modules

---

# 🧱 Phase 1 — Pipeline Foundation

## Task 1.1 — Create Pipeline Context

Create:

```text
pipeline/pipeline_context.py
```

Implement:

* PipelineContext class

Fields:

* raw_text
* metadata
* chunks
* chunk_summaries
* doc_type_result
* extraction_results
* merged_result

---

## Task 1.2 — Create Pipeline Types

Create:

```text
pipeline/pipeline_types.py
```

Define:

```python
PipelineResult = {
  "stage_name": str,
  "success": bool,
  "data": dict,
  "debug": dict,
  "errors": list
}
```

---

## Task 1.3 — Create Pipeline Controller

Create:

```text
pipeline/pipeline_controller.py
```

IMPORTANT:

* naming aligned with existing `pipeline_controller.py`
* DO NOT create "orchestrator"

Implement:

```python
run_pipeline(pipeline_name, text, metadata=None)
```

---

## Task 1.4 — Create Pipeline Config

Create:

```text
pipeline/pipeline_config.py
```

Define:

```python
PIPELINE_CONFIG = {
  "doc_type_aware_extraction": [
    "chunk_summary",
    "doc_type_classification",
    "extraction_multidim",
    "merge_multidim"
  ]
}
```

---

## Task 1.5 — Create Pipeline Utils

Create:

```text
pipeline/pipeline_utils.py
```

Used for:

* shared helpers
* context updates
* stage execution helpers

---

# 🧠 Phase 2 — DocType Classification

## Task 2.1 — Add task setting

Modify:

```text
task_configs/
```

Add:

```
DocType-Classification
```

---

## Task 2.2 — Build doctype helper

Add to:

```text
pipeline/pipeline_utils.py
```

---

## Task 2.3 — Create classification step

Create:

```text
pipeline/steps/doc_type_classification.py
```

---

# 📦 Phase 3 — Chunk Summary

## Task 3.1 — Create chunk summary step

Create:

```text
pipeline/steps/chunk_summary.py
```

---

## Task 3.2 — Add chunk execution

Modify:

```text
pipeline/pipeline_controller.py
```

---

# 🧩 Phase 4 — Prompt Refactor

## Task 4.1 — Base prompt

Create:

```text
prompt_pipeline/prompts/base/
```

---

## Task 4.2 — Overlay prompts

Create:

```text
prompt_pipeline/prompts/overlays/
```

---

## Task 4.3 — Prompt builder

Create:

```text
prompt_pipeline/prompt_builder.py
```

---

# ⚙️ Phase 5 — Extraction

## Task 5.1 — Create extraction step

Create:

```text
pipeline/steps/extraction_multidim.py
```

IMPORTANT:

* must call existing extraction logic

---

## Task 5.2 — Inject doc_type

Ensure:

* all chunks use same doc_type

---

# 🔀 Phase 6 — Merge Refactor

## Task 6.1 — Base strategy

Create:

```text
pipeline/merge/base_strategy.py
```

---

## Task 6.2 — Strategies

Create:

```text
pipeline/merge/
```

Files:

* event_strategy.py
* interview_strategy.py
* profile_strategy.py
* issue_strategy.py
* report_strategy.py
* legal_strategy.py
* mixed_strategy.py

---

## Task 6.3 — Merge selector

Create:

```text
pipeline/merge/merge_selector.py
```

---

## Task 6.4 — Merge step

Create:

```text
pipeline/steps/merge_multidim.py
```

---

# 🔗 Phase 7 — First Pipeline

Update:

```text
pipeline/pipeline_config.py
```

---

## Task 7.2 — Expose API

Expose:

```python
run_pipeline()
```

Keep:

```python
run_extraction()
```

unchanged

---

# 🚀 Phase 8 — Future Extension

Add under:

```text
pipeline/steps/
```

* translation.py
* summarization.py

---

# 🧪 Phase 9 — Testing

## MUST integrate with:

* sql_mode
* handlers
* row_processors

---

# ⚠️ FINAL RULE

> Follow existing naming style over theoretical architecture naming.

---

# ✅ Success Criteria

* pipeline runs end-to-end
* no schema break
* no duplicate systems
* naming consistent with repo

---

# 🧾 Summary

> Extend, don't reinvent. Match naming, don't introduce frameworks.
