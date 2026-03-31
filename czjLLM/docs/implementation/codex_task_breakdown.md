# Codex Execution Plan: Pipeline Upgrade (Step-by-Step)

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

---

# 🧱 Phase 1 — Pipeline Skeleton (Foundation)

## Task 1.1 — Create PipelineContext

**Depends on:** None

Create:

```
agent/pipeline/context.py
```

Implement:

* PipelineContext dataclass

Fields:

* raw_text
* metadata
* chunks
* chunk_summaries
* doc_type_result
* extraction_results
* merged_result

✅ Done when:

* context object can be created without breaking existing code

---

## Task 1.2 — Create StageResult type

**Depends on:** 1.1

Create:

```
agent/pipeline/types.py
```

Define:

```
{
  stage_name,
  success,
  data,
  debug,
  errors
}
```

✅ Done when:

* all new stages return this format

---

## Task 1.3 — Create Orchestrator (minimal)

**Depends on:** 1.1, 1.2

Create:

```
agent/pipeline/orchestrator.py
```

Implement:

* run(pipeline_name, raw_text)

Support:

* sequential execution
* shared context

✅ Done when:

* can run dummy pipeline with 2 mock stages

---

## Task 1.4 — Create Pipeline Registry

**Depends on:** 1.3

Create:

```
agent/pipeline/registry.py
```

Define:

```
PIPELINES = {
  "test_pipeline": ["stage_a", "stage_b"]
}
```

✅ Done when:

* orchestrator reads pipeline from registry

---

# 🧠 Phase 2 — DocType Classification (Stage 1)

## Task 2.1 — Add DocType task setting

**Depends on:** None

Add new task:

```
DocType-Classification
```

Output JSON:

```
doc_type
doc_type_confidence
secondary_type
has_primary_event
routing_reason
```

✅ Done when:

* can classify text independently

---

## Task 2.2 — Build doctype input helper

**Depends on:** 2.1

Create:

```
build_doctype_input()
```

Include:

* title
* head paragraphs
* tail paragraphs
* chunk summaries

✅ Done when:

* classifier input is structured (not raw full text)

---

## Task 2.3 — Implement classification stage

**Depends on:** 1.3, 2.1, 2.2

Create:

```
agent/tasks/doc_type_classification.py
```

Logic:

* build input
* run classification
* write to context.doc_type_result

✅ Done when:

* pipeline can output doc_type

---

# 📦 Phase 3 — Chunk Summary (Support Stage)

## Task 3.1 — Create chunk_summary stage

**Depends on:** 1.3

Create:

```
agent/tasks/chunk_summary.py
```

Each chunk outputs:

* summary
* rough role (optional)

✅ Done when:

* context.chunk_summaries exists

---

## Task 3.2 — Add chunk-level execution support

**Depends on:** 3.1

Update orchestrator:

* support level = chunk | document

✅ Done when:

* chunk_summary runs per chunk
* doc_type runs once per document

---

# 🧩 Phase 4 — Prompt Refactor (Base + Overlay)

## Task 4.1 — Extract base prompt

**Depends on:** None

Create:

```
prompts/base/multidim_base_prompt.py
```

Move:

* shared rules only

---

## Task 4.2 — Create overlay prompts

**Depends on:** 4.1

Create overlays:

* event
* interview
* profile
* issue
* report
* legal
* mixed

---

## Task 4.3 — Create prompt builder

**Depends on:** 4.2

Create:

```
build_multidim_prompt()
```

Inject:

* doc_type
* confidence
* overlay
* content

✅ Done when:

* prompt differs based on doc_type

---

# ⚙️ Phase 5 — Type-aware Extraction

## Task 5.1 — Wrap existing extraction

**Depends on:** 4.3

Create:

```
agent/tasks/extraction_multidim.py
```

Logic:

* read doc_type
* build prompt
* call original extraction

---

## Task 5.2 — Inject doc-level context into chunks

**Depends on:** 5.1

Ensure each chunk gets:

* same doc_type
* same guidance

✅ Done when:

* chunk outputs become more consistent

---

# 🔀 Phase 6 — Merger Refactor (Critical)

## Task 6.1 — Create BaseMergeStrategy

**Depends on:** None

Create:

```
agent/merger/strategies/base_strategy.py
```

---

## Task 6.2 — Implement strategies

**Depends on:** 6.1

Create:

* event
* interview
* profile
* issue
* report
* legal
* mixed

---

## Task 6.3 — Create strategy dispatcher

**Depends on:** 6.2

```
get_merge_strategy(doc_type)
```

---

## Task 6.4 — Integrate merger stage

**Depends on:** 6.3

Create:

```
merge_multidim stage
```

✅ Done when:

* different doc_type → different merge behavior

---

# 🔗 Phase 7 — First Real Pipeline

## Task 7.1 — Register pipeline

**Depends on:** All above

```
doc_type_aware_extraction = [
  chunk_summary,
  doc_type_classification,
  extraction_multidim,
  merge_multidim
]
```

---

## Task 7.2 — Add run_pipeline API

**Depends on:** 7.1

Expose:

```
run_pipeline(name, text)
```

Keep:

```
run_extraction()   ← unchanged
```

---

# 🚀 Phase 8 — Extensibility (Future-proof)

## Task 8.1 — Add translation node

## Task 8.2 — Add summarization node

---

## Task 8.3 — Create second pipeline

```
translate_then_summarize
```

---

# 🧪 Phase 9 — Testing

## Task 9.1 — Prepare test dataset

* event
* interview
* profile
* issue
* report
* legal

---

## Task 9.2 — Validate improvements

Check:

* no fake events
* no timeline pollution
* stable subject/action/object

---

## Task 9.3 — Validate compatibility

Ensure:

* schema unchanged
* ES queries still work
* agent works

---

# ✅ Final Success Criteria

* pipeline runs end-to-end
* doc_type affects extraction
* merger adapts per type
* no schema break

---

# 🧾 Summary

Execute tasks in order.

DO NOT skip dependencies.

First milestone:

> ✅ doc_type_aware_extraction pipeline works end-to-end

Then expand.

---
