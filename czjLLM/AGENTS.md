# AGENTS.md

## Purpose

This repository is an LLM-based analysis system that currently uses task settings plus parallel chunk processing to produce fixed-schema structured outputs.

The current upgrade goal is:

> Evolve the system into a **composable multi-stage LLM pipeline**
> while preserving backward compatibility.

Codex must treat this repository as an **incremental refactor project**, not a rewrite.

---

## Primary references

Before making architecture changes, read these files first:

1. `ARCHITECTURE.md`
2. `docs/architecture/pipeline_architecture_upgrade.md`
3. `docs/implementation/codex_task_breakdown.md`

If implementation details conflict with intuition, prefer the architecture and task breakdown docs.

---

## Repository priorities

When changing this project, prioritize the following in order:

1. **Do not break existing fixed JSON output schema**
2. **Do not break existing ES / agent query compatibility**
3. **Prefer wrapper / extension / overlay over destructive rewrite**
4. **Keep changes incremental and testable**
5. **Preserve current extraction functionality while adding pipeline capability**

---

## High-level architecture direction

The repository is moving from:

```text
Task Setting → Input Text → LLM → JSON Output