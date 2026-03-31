# Architecture Overview

## System Evolution

This project is evolving from a:

> **Single-stage LLM extraction system**

into a:

> **Composable Multi-Stage LLM Pipeline Platform**

---

## 🧠 Core Idea

Instead of:

```
Task → LLM → Output
```

We move to:

```
Input
→ Stage A
→ Stage B
→ Stage C
→ Output
```

Each stage is:

* Reusable
* Independent
* Composable

---

## 🔩 Key Components

### 1. Node (Stage)

A reusable unit of computation:

Examples:

* DocType Classification
* Translation
* Summarization
* Extraction
* Merger

Each node defines:

* Input schema
* Output schema
* Prompt
* Execution type (chunk / document)

---

### 2. Pipeline

An ordered sequence of nodes.

Example:

```
DocType Classification
→ Extraction
→ Merger
```

---

### 3. Orchestrator

Responsible for:

* Running pipelines
* Passing data between stages
* Managing chunk-level vs document-level execution
* Supporting future routing logic

---

## 🧱 Execution Model

### Chunk-Level Stages

* Operate per chunk
* Parallelizable

Examples:

* Chunk Summary
* Local Extraction

---

### Document-Level Stages

* Operate on global context

Examples:

* DocType Classification
* Final Merger

---

## 🧪 First Implemented Pipeline

### doc_type_aware_extraction

```
Raw Text
→ Chunking
→ Chunk Summaries
→ DocType Classification
→ Type-aware Extraction
→ Type-aware Merger
→ Final Output
```

---

## 🧩 Why DocType Matters

Different document types require different extraction strategies:

| Type      | Behavior            |
| --------- | ------------------- |
| event     | single event focus  |
| interview | Q&A + statements    |
| profile   | career narrative    |
| issue     | trend / problem     |
| report    | structured findings |
| legal     | rules / agreements  |

Without classification, extraction becomes unstable.

---

## 🧠 Design Constraints

### MUST keep:

* Fixed JSON schema
* Agent compatibility
* Elasticsearch compatibility

### MUST NOT:

* Introduce multiple schemas
* Break existing queries
* Fragment data structure

---

## 🔄 Prompt Architecture

Move from:

```
One giant prompt
```

to:

```
Base Prompt
+ Type Overlay
```

---

## 🔀 Merger Strategy

Different doc_types require different merging logic:

* Event → select single core event
* Interview → preserve interview context
* Profile → avoid fake timelines
* Issue → avoid fake event construction
* Report → reduce noise
* Legal → keep structure minimal

---

## 🔮 Future Extensions

This architecture enables:

### Translation Pipeline

```
Language Detection → Translation → Summary
```

### Knowledge Preparation

```
Chunk Summary → Global Summary → Entity Extraction
```

### Retrieval Optimization

```
Extraction → Canonicalization → Index Formatting
```

---

## 📍 Full Specification

Detailed implementation spec:

👉 `docs/architecture/pipeline_architecture_upgrade.md`

---

## 🧾 Summary

This is not a rewrite.

This is:

> **A controlled evolution from a single-task system into a modular LLM pipeline platform.**

Key benefits:

* Better extraction quality
* More flexible workflows
* Future-proof architecture
* Reusable components

---

## End
