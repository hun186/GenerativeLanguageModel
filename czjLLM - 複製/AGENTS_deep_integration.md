# AGENTS.md (Deep Integration Edition)

## Goal

Refactor this repository into a:

> **Deeply Integrated Composable Multi-Stage LLM Pipeline System**

While STRICTLY:

- preserving existing behavior
- preserving output schema
- NOT breaking prompt_pipeline execution layer
- integrating with existing parallel / dispatch / monitoring mechanisms
- using minimal invasive changes first, then controlled optimization

---

## Critical Constraints (MUST FOLLOW)

### 1. DO NOT break existing system

- Existing extraction must still work
- Existing JSON schema must NOT change
- Existing downstream handlers / writers must remain compatible
- Existing public entry points must remain usable

---

### 2. DO NOT move LLM logic into `pipeline/`

LLM-related code MUST stay in:

```text
prompt_pipeline/
```

`pipeline/` is ONLY for:

- orchestration
- context passing
- stage coordination
- merge strategy selection
- pipeline config

---

### 3. Deeply integrate with existing runtime

You MUST scan and reuse existing mechanisms for:

- chunk parallelism / multiprocessing
- dispatcher / scheduler / task router
- monitoring / logging / tracing
- downstream output handling

Bad approach:

- create a neat but isolated pipeline that ignores the real runtime

Good approach:

- make pipeline stages execute within the current runtime model

---

### 4. Prefer ADDITION over DELETION, WRAPPER over REWRITE

Good:

- wrap existing functions
- add new modules
- integrate into existing runtime hooks
- extend behavior behind compatible entry points

Bad:

- rewrite core logic
- replace stable operational code without proof
- bypass existing runtime and handlers

---

### 5. Pipeline is a native upgrade, not a sidecar system

Correct structure:

```text
existing runtime / dispatcher
→ pipeline/
→ prompt_pipeline/
```

Not:

```text
new side pipeline
→ separate execution world
```

---

### 6. All stages must be independently testable

Each step must:

- accept explicit input
- return structured result
- not depend on hidden global state
- support mock / fake LLM testing
- support integration testing with runtime-adapter shims where needed

---

## Architecture Rules

### Layer Separation

| Layer | Responsibility |
|---|---|
| prompt_pipeline | prompt + LLM execution |
| pipeline | workflow orchestration |
| existing runtime | dispatch / parallel / monitoring / downstream |

---

### PipelineContext is REQUIRED

All stages must read/write via `PipelineContext`.

The context should also be able to carry:

- runtime metadata
- trace / stage debug info
- identifiers needed by monitoring or downstream logic

---

### Output MUST be wrapped

Final output MUST follow `PipelineOutput`.

BUT:

- `data` MUST preserve original format
- existing structured extraction schema must remain unchanged
- old consumers should still be able to do `result = output["data"]`

---

## Mandatory implementation behavior

### Before writing code, you MUST scan the repo and identify:

- LLM call locations
- prompt assembly locations
- extraction main flow
- chunk split path
- parallel worker / multiprocessing path
- dispatcher / scheduling / task-routing path
- monitoring / logging / progress hooks
- merge logic
- task config / pipeline config locations
- downstream output writers (txt / DB / ES / handlers / row processors)

You must then explicitly classify:

1. what will be reused directly
2. what will be wrapped
3. what must be minimally modified
4. what new files belong purely to orchestration
5. what existing runtime hooks must be integrated rather than bypassed

No implementation should start before this analysis is made.

---

## Implementation Strategy

### Phase 1 — Stable landing

Required order:

1. repo scan + reuse / runtime integration analysis
2. PipelineContext
3. pipeline config / YAML loader
4. pipeline controller
5. chunk_summary
6. doc_type_classification
7. extraction wrapper
8. merge strategies
9. merge_multidim
10. pipeline registration and end-to-end flow
11. mock LLM path
12. pytest minimal tests
13. smoke demo
14. runtime integration pass (dispatcher / monitoring / downstream hooks fully wired if not already)

### Phase 2 — Controlled optimization

Only after Phase 1 is passing:

- selective refactor
- merger logic optimization
- prompt overlay refinement
- chunking improvements
- performance improvements
- simplification under test protection

---

## Forbidden

- rewriting `prompt_pipeline/`
- duplicating extraction logic into a second system
- creating multiple incompatible schemas
- creating a detached pipeline runner that ignores current runtime
- bypassing monitoring / dispatch / handler paths without strong reason
- introducing unrelated cleanup or framework churn
- relying on real LLM APIs for tests

---

## Success Criteria

- pipeline runs end-to-end
- doc_type affects extraction
- merger changes behavior by doc_type
- old system still works
- output schema unchanged
- runtime integration is real, not superficial
- monitoring / downstream compatibility is preserved

---

## Mental Model

Think:

> add a pipeline brain, wire it into the existing body, and keep the organism alive

---

## Final Rule

When unsure, choose:

- smallest change
- deepest reuse
- strongest compatibility
- highest testability
- least duplication
