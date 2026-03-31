# LLM Pipeline Upgrade

## Overview

This project upgrades an existing LLM-based analysis system into a:

> **Composable Multi-Stage Pipeline Architecture**

WITHOUT breaking:

* existing prompt execution logic
* existing output schema
* existing downstream usage

---

## 🧠 Core Idea

Old:

Task → LLM → Output

New:

Input
→ Pipeline (multi-stage)
→ Output (same format)

---

## 🧱 Architecture

### Layer 1 — prompt_pipeline/

Handles:

* prompt construction
* LLM calls
* retry / fallback
* result parsing

### Layer 2 — pipeline/

Handles:

* workflow orchestration
* stage sequencing
* context passing
* merge strategy

---

## 🔄 First Pipeline

### doc_type_aware_extraction

```
Text
→ Chunk Summary
→ DocType Classification
→ Extraction (type-aware)
→ Merge (type-aware)
→ JSON Output
```

---

## 📦 Output

Pipeline returns:

```
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

* `data` keeps original format
* no schema breaking

---

## 🚀 Why This Matters

This enables:

* better extraction accuracy
* document-type awareness
* extensibility (translation, summary, etc.)
* reusable pipeline system

---

## 🛠 Future Extensions

* translation pipeline
* summarization pipeline
* knowledge preprocessing
* multi-task chaining

---

## ⚠️ Important

This project is:

> **an extension layer, NOT a rewrite**

---

## 🧩 Key Principle

> "Composable, not destructive"
