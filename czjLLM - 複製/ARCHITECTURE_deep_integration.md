# Architecture Overview (Deep Integration Edition)

## System Evolution

This project should evolve from:

> **Single-task / task-setting driven LLM execution with existing parallel runtime**

into:

> **Deeply Integrated Composable Multi-Stage LLM Pipeline System**

This is **not** a detached scaffold.

This upgrade must plug into the repository's **existing**:

- task-setting / task-config execution path
- chunk parallelism / worker pool / multiprocessing model
- dispatch / routing / scheduling flow
- monitoring / logging / tracing / status reporting
- downstream writers (txt / DB / ES / handlers / row processors)

---

# Core Idea

From:

```text
Task Setting
→ Existing Dispatcher / Parallel Runtime
→ Prompt Execution
→ Chunk Results
→ Existing Merge / Downstream
```

To:

```text
Input
→ Existing Dispatcher / Parallel Runtime
→ Multi-Stage Pipeline (deeply integrated)
→ Stage-aware Chunk Execution
→ Doc-level Routing / Merge
→ Existing Downstream Interfaces
```

---

# Critical Architecture Principle

## Deep integration, not sidecar orchestration

The new pipeline layer MUST NOT become an isolated side system that bypasses the current runtime.

Instead, it must be built so that:

1. existing runtime infrastructure is reused as much as possible
2. pipeline stages can execute through current worker / parallel execution paths
3. monitoring and dispatch remain first-class, not optional extras
4. legacy entry points remain valid
5. the first pipeline (`doc_type_aware_extraction`) can run inside the current production-style flow

---

# Required Three-Part Responsibility Split

## Part 1 — `prompt_pipeline/`

Responsible for:

- prompt construction
- LLM calls
- retry / fallback
- result parsing

This remains the execution layer for model interaction.

## Part 2 — `pipeline/`

Responsible for:

- workflow orchestration
- stage sequencing
- PipelineContext passing
- doc-level routing
- merge strategy selection
- stage contracts / pipeline config

## Part 3 — existing runtime / system integration layer

The already-existing repository mechanisms for:

- parallel chunk execution
- process / worker orchestration
- job dispatch
- monitoring / logging / progress tracking
- downstream output handling

must be reused and wired into pipeline execution rather than bypassed.

---

# Final Layer Rule

> `prompt_pipeline/` executes model work  
> `pipeline/` decides stage flow  
> existing runtime executes the real operational workload

---

# Architecture Shape

## Existing runtime stays operationally central

The pipeline upgrade must preserve the current operational heart of the system.

That means:

- chunk-level stages should run through existing parallel execution capability whenever the repo already has it
- document-level stages should still emit logs / monitoring signals through the current observability path
- existing task settings and handlers should remain discoverable and reusable
- downstream txt / DB / ES integrations must continue to consume compatible outputs

---

# Key Concepts

## 1. Stage

A reusable processing unit, but not a detached framework abstraction.

Examples:

- chunk_summary
- doc_type_classification
- extraction_multidim
- merge_multidim

Each stage must be callable in a way that can be executed within the existing runtime.

## 2. Pipeline

An ordered stage composition such as:

```text
chunk_summary
→ doc_type_classification
→ extraction_multidim
→ merge_multidim
```

## 3. Pipeline Controller

Responsible for:

- orchestrating stage order
- coordinating chunk-level vs document-level steps
- integrating with current dispatch / worker execution path
- preserving current public entry points

## 4. PipelineContext

Shared state for pipeline stages.

Must at minimum store:

- raw_text
- article_title
- article_date_iso
- chunks
- chunk_summaries
- doc_type_result
- extraction_results
- merged_result
- metadata
- runtime trace / stage trace hooks

---

# Execution Model

## Chunk-Level Stages

These should:

- operate per chunk
- be parallelizable
- preferentially reuse existing worker / multiprocessing / dispatch machinery
- support stage metadata for monitoring

Examples:

- chunk_summary
- extraction_multidim

## Document-Level Stages

These should:

- run once per document
- preserve traceability and monitoring
- feed document-level guidance back into chunk-level stages

Examples:

- doc_type_classification
- merge_multidim

---

# Operational Integration Requirements

## 1. Dispatch integration

The pipeline must integrate with the repository's current dispatch / routing flow.

Bad:

```text
new pipeline runner → ignores existing dispatcher
```

Good:

```text
existing dispatcher
→ pipeline-aware execution path
→ stage execution
```

## 2. Parallel runtime integration

The new chunk stages must not replace a mature existing multiprocessing / parallel framework with a simplistic loop unless no such mechanism exists.

## 3. Monitoring integration

All stages should support propagation of:

- stage name
- chunk index
- document id / task id if available
- success / failure
- timing / debug metadata where feasible

## 4. Downstream integration

The final result must remain compatible with:

- txt writing
- DB writing
- ES indexing
- row processors / handlers / SQL mode if present

---

# Output Interface

All pipelines return:

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

- `data` preserves the original downstream-facing format
- structured extraction schema must remain compatible
- pipeline metadata may include doc_type / trace info, but should not break old consumers

---

# First Deep-Integration Pipeline

## `doc_type_aware_extraction`

```text
Raw Text
→ Existing Chunking Path
→ Chunk Summary
→ DocType Classification
→ Type-aware Extraction
→ Type-aware Merge
→ Existing Downstream-Compatible Output
```

This pipeline must be implemented so it can reuse the current system's real execution path, not only a local demo path.

---

# Why Deep Integration Matters

A shallow scaffold is not enough because this repository already appears to have meaningful infrastructure for:

- chunk parallelization
- worker / dispatch flow
- monitoring / status tracking
- downstream persistence / indexing

If the new pipeline ignores that infrastructure, the repo ends up with:

- duplicate execution paths
- harder maintenance
- inconsistent logging / monitoring
- divergent runtime behavior between old and new tasks

The correct goal is:

> **one operational system, upgraded with stage-awareness**

---

# Design Constraints

## MUST KEEP

- existing JSON schema for structured extraction
- existing prompt_pipeline as the model execution layer
- backward compatibility of public entry points
- existing runtime capabilities when available
- existing monitoring / downstream integration

## MUST NOT

- rewrite prompt_pipeline into pipeline/
- build a detached toy pipeline that bypasses real runtime
- create a second incompatible dispatch path
- remove or sideline current multiprocessing / monitoring / handler logic
- force all outputs into one new schema

---

# Implementation Orientation

The repository should move toward:

> **Pipeline-aware execution built on top of the current production runtime**

not toward:

> **A separate demo pipeline next to the real system**

---

# Summary

This is not merely:

> add a scaffold on top of an LLM system

This is:

> **upgrade the existing operational system so pipeline stages become native to its real runtime**

---

# Final Principle

> Add a pipeline brain, and connect it to the existing nervous system
