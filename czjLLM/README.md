# LLM Multi-Dimensional Analysis System

## Architecture
- `ARCHITECTURE.md`
- `docs/architecture/pipeline_architecture_upgrade.md`

## Codex execution plan
- `AGENTS.md`
- `docs/implementation/codex_task_breakdown.md`

## Overview

This project provides a **multi-dimensional information extraction system powered by LLMs**, designed to process long-form text and produce structured, SQL-friendly JSON outputs.

Key capabilities:

* Long document processing (chunking + parallel analysis)
* Multi-dimensional structured extraction
* Evidence-based outputs
* Designed for downstream retrieval and agent workflows

---

## 🚀 Current Capabilities

* Fixed-schema JSON extraction (`multidim_event_json`)
* Parallel chunk processing for long documents
* Evidence-backed extraction (no hallucination-first design)
* Compatible with Elasticsearch / Kibana workflows

---

## 🔄 Ongoing Upgrade (Important)

This system is currently being upgraded to a:

> **Composable Multi-Stage LLM Pipeline Architecture**

This upgrade introduces:

* Document-level intelligence (doc_type classification)
* Multi-stage processing (classification → extraction → merge)
* Reusable pipeline stages (translation, summary, extraction, etc.)
* Better handling of non-event texts (interview / profile / issue / report / legal)

👉 Full design spec:
**`docs/architecture/pipeline_architecture_upgrade.md`**

---

## 🧠 Why This Upgrade?

Previously, all texts were processed using a single extraction strategy.

This caused issues such as:

* Interviews being forced into event format
* Profiles turning into fake timelines
* Reports polluting event structures
* Issue analysis being misinterpreted as single events

The new architecture solves this via:

* Document-level classification
* Type-aware extraction
* Type-aware merging

---

## 🧩 Example Pipeline

### doc_type-aware extraction

```
Raw Text
→ Chunking
→ Chunk Summaries
→ DocType Classification
→ Type-aware Extraction
→ Type-aware Merger
→ Final JSON
```

---

## 🧱 Project Structure (Simplified)

```
project-root/
  agent/
    pipeline/
    tasks/
    prompts/
    merger/
  docs/
    architecture/
```

---

## ⚙️ Usage (Current)

```python
result = run_extraction(task="InfoExtraction-MultiDim", text=input_text)
```

---

## ⚙️ Usage (Future Pipeline)

```python
result = run_pipeline(
    pipeline="doc_type_aware_extraction",
    text=input_text
)
```

---

## 📚 Documentation

* Architecture: `docs/architecture/pipeline_architecture_upgrade.md`
* (Future) Pipelines: `docs/pipelines/`
* (Future) Tasks: `docs/tasks/`

---

## 🧭 Design Principles

* Fixed output schema (agent-compatible)
* Evidence-first extraction
* Conservative inference (avoid hallucination)
* Modular, composable pipeline design

---

## 🔧 Status

* [x] Core extraction system
* [x] Parallel processing
* [ ] DocType classification (in progress)
* [ ] Pipeline orchestrator (in progress)
* [ ] Type-aware merger (in progress)

---

## 🧾 License

Internal / Project-specific
