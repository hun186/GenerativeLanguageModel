# LLM Pipeline Upgrade (Deep Integration Edition)

## Overview

This project upgrades an existing LLM-based analysis system into a:

> **Deeply Integrated Composable Multi-Stage Pipeline Architecture**

WITHOUT breaking:

- existing prompt execution logic
- existing output schema
- existing downstream usage
- existing chunk parallelism / dispatch / monitoring infrastructure

---

## Core Idea

Old:

```text
Task Setting
→ Existing Runtime
→ LLM Execution
→ Output
```

New:

```text
Input
→ Existing Runtime + Pipeline Orchestration
→ Multi-Stage Execution
→ Output (same downstream-compatible format)
```

---

## What “Deep Integration” means here

This project should **not** create a detached pipeline framework that only works in isolation.

It **must**:

- reuse the current task-setting structure where feasible
- reuse existing chunking and parallel execution paths where they already exist
- reuse current monitoring / logging / progress reporting hooks
- preserve current downstream writers and handlers
- support old flows and new pipeline flows in the same operational system

---

## Architecture

### Layer 1 — `prompt_pipeline/`

Handles:

- prompt construction
- LLM calls
- retry / fallback
- result parsing

### Layer 2 — `pipeline/`

Handles:

- workflow orchestration
- stage sequencing
- context passing
- merge strategy
- pipeline config

### Layer 3 — existing runtime integration

Handles:

- multiprocessing / parallel execution
- dispatch / routing / scheduling
- monitoring / tracing / logging
- downstream output handling

---

## First Pipeline

### `doc_type_aware_extraction`

```text
Text
→ Chunk Summary
→ DocType Classification
→ Extraction (type-aware)
→ Merge (type-aware)
→ JSON Output
```

But operationally, this pipeline should run through the existing runtime path rather than a detached runner whenever possible.

---

## Output

Pipeline returns:

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

Important:

- `data` keeps original format
- no schema breaking
- metadata can add trace / doc_type context without breaking old consumers

---

## Why this matters

This enables:

- better extraction accuracy
- document-type awareness
- extensibility (translation, summary, canonicalization, etc.)
- reuse of current production-style operational capabilities
- one system instead of parallel overlapping systems

---

## Deep-Integration Success Criteria

A successful implementation should mean:

1. old extraction path still works
2. new pipeline path works end-to-end
3. chunk-level stages can run through existing parallel execution infra
4. monitoring still sees the work
5. downstream handlers still consume results
6. no second disconnected “mini framework” is created

---

## Future Extensions

- translation pipeline
- summarization pipeline
- knowledge preprocessing
- retrieval optimization
- canonicalization / index formatting

These should inherit the same deep-integration principle.

---

## Important

This project is:

> **an extension and integration upgrade, NOT a detached rewrite**

---

## Key Principle

> Composable, integrated, backward-compatible
