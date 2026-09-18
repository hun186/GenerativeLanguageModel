# Reduction Engine v1 — Architecture and Incremental Delivery Plan

Status: Draft for repository-wide Codex architecture review  
Baseline: `c834959d8482e96ab3e815278aec2137952df8d7` (`main`)  
Scope: design only; no production behavior changes in this branch

## 1. Why this project exists

czjLLM already supports:
- generic document slicing and parallel LLM calls;
- simple slice result combination such as text concatenation, JSON-list flatten/concatenation, and audited deep dict merge;
- explicit multi-stage task pipelines;
- output-profile validation/normalization at writeback boundaries;
- per-model and per-slice parallelism controls.

The missing abstraction is a first-class reduction layer between parallel slice outputs and the final stage/output contract.

Recent multidimensional-event failures expose the architectural gap:
- each slice independently emits local `event_id` values such as `E1`, so list concatenation creates identifier collisions;
- article-level scalars such as title/date/summary/importance conflict across slices and cannot be resolved correctly by generic `prefer_left`;
- semantic duplicate events can span overlapping slices;
- strict output profiles correctly reject the resulting invalid global structure.

The same gap also limits future hierarchical aggregation such as:

`10000 pages -> slice summaries -> 50 pages -> re-slice/reduce -> 10 pages -> re-slice/reduce -> 2 pages`

The target is therefore **not a multidim-only reducer**. The target is an extensible Reduction Engine that preserves current simple reducers while enabling task-specific, structured, semantic, and adaptive hierarchical reduction.

## 2. Core architectural principle

Keep four concerns separate:

1. **Stage / task orchestration** — what business operation runs next.
2. **Map / slice execution** — how an input is divided and processed in parallel.
3. **Reduction Engine** — how N slice/stage-local outputs become a smaller/global result, potentially over multiple rounds.
4. **Output Profile** — how the final result is normalized/validated/serialized for a sink.

A reduction **round is not a stage**. A multi-stage pipeline may contain a stage whose internal reduction controller performs one or many rounds.

## 3. Existing boundaries that must be preserved

### 3.1 Legacy combine path

`czjLLM/utilities/combine_utils.py::combine_api_finished_item()` currently:
- reads Success slice files;
- detects text vs JSON-task behavior;
- concatenates text;
- flattens JSON-list slice outputs;
- optionally invokes audited deep dict merge through `slice_merge.py`;
- writes the combined artifact.

This path is widely reused and must remain backward compatible.

### 3.2 Legacy audited dict slice merge

`czjLLM/utilities/slice_merge.py` currently provides:
- `should_merge_slices(ctx)`;
- `merge_dict_slices()`;
- `merge_dict_slices_audited()`.

These functions should initially be wrapped/adapted, not rewritten.

### 3.3 Existing doc-type merge strategies

`czjLLM/pipeline/merge/` already contains `BaseMergeStrategy` and doc-type-specific strategies selected by `merge_selector.py`.

This is a separate semantic domain and must not be silently replaced by the new Reduction Engine. The Codex review must determine whether these strategies should remain internal to the existing pipeline, become adapters into the Reduction Engine later, or share a low-level protocol without changing behavior.

### 3.4 Output Profile

`czjLLM/es_mode/output_profiles/registry.py` already demonstrates a good registry/plugin pattern.

Reducer profiles should follow the same spirit but must not absorb output-profile responsibility.

## 4. Proposed conceptual model

### 4.1 Reducer Profile

A Reducer Profile answers:

> Given a collection of slice outputs for one reduction round, how should they be combined?

Initial built-in profiles should include adapters for existing behavior:

- `concat_text`
- `concat_json_list`
- `legacy_json_deep_merge`

Future profiles:

- `entity_union`
- `structured_relational`
- `semantic_llm`
- `composite`

### 4.2 Reduction Controller

A Reduction Controller answers:

> Is one reduce pass enough? If not, how should another round be created and when should reduction stop?

Initial controllers:

- `single_pass` — default and legacy-compatible.
- `fixed_rounds` — deterministic N-round operation.
- `adaptive_hierarchical` — continue while deterministic stop criteria are not met.

### 4.3 Reduction Policy

Policy controls orchestration rather than task semantics:

- input/token budget per round;
- chunk budget and overlap;
- target output token/character/record budget;
- maximum rounds;
- minimum useful reduction ratio / stall detection;
- maximum fan-in;
- retry/error behavior;
- persistence/resume policy;
- optional reducer changes by round.

### 4.4 Reducer Result

Reducers should return a structured result rather than a naked payload.

Candidate contract:

```python
ReducerResult(
    payload=...,
    profile="...",
    changed=True,
    warnings=[],
    audit={},
    provenance={},
    metrics={
        "input_items": ...,
        "input_tokens": ...,
        "output_tokens": ...,
        "reduction_ratio": ...,
    },
)
```

Exact type and serialization contract must be decided after repository-wide analysis.

## 5. Configuration direction

Do not break existing configuration.

If no new reduction config is present, existing behavior must remain unchanged.

Candidate opt-in syntax:

```yaml
reduction:
  profile: concat_text
  controller: single_pass
```

Hierarchical example:

```yaml
reduction:
  profile: semantic_llm
  controller: adaptive_hierarchical

  target:
    max_tokens: 3000

  chunk:
    max_tokens: 24000
    overlap_tokens: 500

  stop:
    max_rounds: 6
    min_reduction_ratio: 0.15
```

Composite example:

```yaml
reduction:
  profile: composite
  steps:
    - concat_json_list
    - entity_union
```

Round-aware example:

```yaml
reduction:
  controller: adaptive_hierarchical
  rounds:
    - profile: entity_preserving_summary
    - profile: semantic_summary
    - profile: executive_summary
  target:
    max_tokens: 3000
```

These names are provisional. Codex must first map existing config-loading conventions and determine the least disruptive schema.

## 6. Backward-compatibility contract

The project is not allowed to gain Reduction Engine features by changing existing task output unexpectedly.

Golden compatibility requirements:

1. Existing plain text concatenation remains byte-equivalent when new reduction config is absent.
2. Existing JSON-list concatenation/flattening remains shape-equivalent and ordering-equivalent.
3. Existing `merge_slices=true` deep dict merge remains behavior-equivalent, including audit/conflict policy.
4. Existing `merge_slices=false` behavior remains unchanged.
5. Existing multi-stage task sequencing remains unchanged.
6. Existing output-profile validation and writeback contracts remain unchanged.
7. Existing stage-specific writeback sources remain distinguishable from combined sources.
8. Existing public/import compatibility facades such as `combine_utils.py` remain usable during migration.

## 7. Delivery phases

### Phase 0 — Repository-wide architecture inventory and contract freeze

No production changes.

Codex must map:
- every caller of `combine_api_finished_item()`;
- every use of `merge_slices`, `enable_slice_merge`, and `merge_strategy`;
- existing JSON-list concatenation paths;
- all multi-stage configuration and scheduler paths;
- stage barriers and stage output manifests;
- `pipeline/merge/` responsibilities and active usage;
- output-profile resolution and plugin loading;
- token counting/context-budget utilities;
- retry, job-state, cleanup, and resume semantics;
- all tests that characterize combine/merge behavior.

Deliver:
- current-state data-flow diagrams;
- boundary table;
- compatibility matrix;
- risk register;
- proposed package/module locations;
- finalized v1 config contract;
- test plan.

### Phase 1 — Reducer Registry + legacy adapters

Goal: introduce the abstraction with **zero intended behavior change**.

Implement:
- reducer protocol/base type;
- registry with canonical names, aliases, plugin loading consistent with project conventions;
- `concat_text` adapter;
- `concat_json_list` adapter;
- `legacy_json_deep_merge` adapter wrapping current audited merge;
- `single_pass` controller;
- structured `ReducerResult`.

Integration rule:
- existing combine path remains authoritative;
- new registry may initially be invoked behind an adapter/facade;
- no user must add new config.

Exit criteria:
- golden tests prove old behavior is unchanged;
- no output-profile or multi-stage changes.

### Phase 2 — Opt-in Reduction Engine routing

Goal: allow tasks to opt into `reduction.profile` without disturbing legacy tasks.

Implement:
- config parser/normalizer;
- validation of profile/controller names and options;
- explicit diagnostics showing selected reducer/controller;
- audit propagation;
- plugin hooks.

Exit criteria:
- legacy configurations remain unchanged;
- opt-in concat/list/deep-merge profiles reproduce legacy outputs.

### Phase 3 — Hierarchical Reduction Controller v1

Goal: support repeated reduction rounds safely.

Implement:
- `fixed_rounds`;
- `adaptive_hierarchical`;
- deterministic stop conditions based on token/character/record budgets;
- max-round guard;
- stall detection using reduction ratio;
- per-round metrics/audit;
- stable round/chunk ordering;
- intermediate artifacts with atomic writes;
- restart/resume from completed round where compatible with current job model.

The first functional use case should be text summarization, not multidim, because its acceptance contract is easier to isolate.

Required scenario:
- oversized text -> map summaries -> reduce;
- if reduced result still exceeds target, re-slice the reduced result and repeat;
- terminate when target reached or stop guard fires.

### Phase 4 — Composite deterministic reducers

Goal: make reducers reusable building blocks.

Candidates:
- `entity_union`;
- exact/canonical dedup helpers;
- configurable list union;
- field-aware scalar policies;
- `composite` reducer pipeline.

No LLM reducer is required yet.

### Phase 5 — Semantic LLM reducer

Goal: permit a reduction round itself to invoke an LLM for global consolidation.

Requirements:
- reuse existing model/client/parallelism infrastructure rather than create a second LLM stack;
- explicit reducer prompt/task configuration;
- token-budget enforcement;
- audit usage integrated with existing LLM call audit;
- deterministic outer controller remains responsible for stop decisions;
- semantic reducer failure must not silently fall back to unsafe structural merge unless configured.

### Phase 6 — Structured relational reducer

Goal: support globally coherent structured outputs that contain local identifiers and cross references.

Generic capabilities:
- slice-local identifier namespace;
- reference remapping;
- provenance retention;
- collision detection;
- integrity checks;
- optional semantic duplicate consolidation;
- final canonical identifier assignment.

The multidimensional-event task becomes the first production consumer, but the reducer must not hard-code only `Event/event_id/event_ids` if a generic field mapping can express the contract cleanly.

Example config direction:

```yaml
reduction:
  profile: structured_relational
  id_fields:
    Event: event_id
  reference_fields:
    - Person.event_ids
    - Involved_Parties.event_ids
    - Impact.event_ids
    - Event_Timeline.event_ids
    - evidence_snippets.event_ids
```

Final exact schema should be decided after Phase 0 analysis.

### Phase 7 — Multi-stage integration and round-aware profiles

Goal: let any stage choose a reduction policy while preserving stage semantics.

Support:
- no reducer;
- one-pass reducer;
- hierarchical reducer inside one stage;
- reducer profile changing by round;
- reducer output feeding the next explicit business stage.

Critical rule:
- **rounds remain internal to a stage**;
- existing stage manifests/writeback selectors must not mistake rounds for additional stages.

### Phase 8 — Production hardening and operational visibility

Add:
- metrics for rounds/chunks/tokens/reduction ratio;
- bounded audit logs;
- clear stop reason (`target_reached`, `max_rounds`, `stalled`, `error`);
- failure/retry semantics;
- cancellation behavior;
- cleanup/retention policy for intermediate artifacts;
- concurrency limits for nested map/reduce so hierarchical reduction cannot oversubscribe GPUs/endpoints;
- end-to-end ES/SQL/file regression tests.

## 8. Multidimensional-event problem as acceptance case, not architecture driver

The current multidim failure demonstrates why the engine is needed:
- per-slice `E1` identifiers collide;
- linked `event_ids` become ambiguous;
- article-level scalars conflict;
- generic list concat/deep merge cannot perform semantic event reconciliation.

However, do not solve v1 by placing multidim-specific branches inside generic combine code.

Use it as an acceptance test for Phase 6:
- two or more slices may each contain local `E1`;
- final output contains globally unique canonical event IDs;
- every reference resolves;
- overlapping semantic events may be consolidated by an explicit semantic step;
- final payload passes the unchanged multidim output profile.

## 9. Hierarchical-summary acceptance case

A reference acceptance scenario should cover:

`very large source -> round 1 -> still over target -> round 2 -> still over target -> round 3 -> target reached`

Assertions:
- each round uses the previous round's output, not the original entire source;
- order/provenance is preserved where required;
- round metrics are recorded;
- controller stop decision is deterministic;
- no unbounded recursion;
- process can resume from a completed intermediate round when supported;
- final output enters the next stage/output path exactly once.

## 10. Testing strategy

### Contract/golden tests
Capture current behavior before routing changes:
- text concat;
- JSON list concat;
- deep dict merge with conflicts/dedup;
- no-merge path;
- ordering;
- empty/malformed slice handling;
- multistage stage-source writeback;
- output profile validation.

### Reducer unit tests
- registry aliases/plugins;
- reducer input/output contracts;
- audit and metrics;
- deterministic ordering;
- error types.

### Controller tests
- target reached after one round;
- multiple rounds;
- max-round stop;
- stall stop;
- empty output;
- growing output;
- reducer error;
- cancellation;
- resume.

### Integration tests
- legacy single-stage;
- explicit multi-stage;
- SQL/ES row-merger source resolution;
- hierarchical summary;
- structured relational multidim.

## 11. Safety and failure semantics

- Never weaken an output profile merely to make a reducer result pass.
- Never silently guess semantic conflict resolution in a deterministic reducer.
- Invalid structured output should remain observable.
- Semantic repair/consolidation must be explicit and auditable.
- No infinite hierarchical recursion.
- Nested reduction concurrency must respect existing model/slice parallelism controls.
- Intermediate artifacts must use existing atomic I/O utilities where possible.
- Secrets/endpoints must not be persisted in reducer audits or project memory.

## 12. Open questions for Codex architecture review

1. Where is the lowest-risk integration seam: inside `combine_api_finished_item()`, immediately before it, or through a new facade it delegates to?
2. Which existing JSON-list combination behavior is relied upon externally and must be captured as golden tests?
3. Is `pipeline/merge/` actively used by the same runtime path as `prompt_pipeline`, or is it a separate/experimental pipeline?
4. How should reducer plugin loading align with output-profile plugin loading without creating circular dependencies?
5. What token-counting utility is authoritative for adaptive stop decisions?
6. Where should round manifests/intermediate artifacts live so SQL/ES/TXT modes can resume safely?
7. How should job cancellation and pending/running state interact with nested reduction rounds?
8. Should a semantic reducer reuse the current task/stage model or use a dedicated reducer task declaration?
9. How can hierarchical reduction reuse existing slice parallelism without nested oversubscription?
10. What is the minimal generic contract for structured identifiers/references without overengineering a graph framework?

## 13. Definition of success

The project is successful when:
- existing tasks behave exactly as before unless they explicitly opt into new reduction behavior;
- simple tasks stay simple and cheap;
- advanced tasks can select richer reducers;
- a stage can perform adaptive multi-round reduction;
- multidim/global relational outputs can be reduced without local-ID collisions;
- output profiles remain the final validation boundary;
- multi-stage orchestration remains clear and unchanged in meaning;
- new reducers can be added through a registry/plugin contract rather than by editing a central `if task == ...` block.

## 14. Recommended immediate next action

Do **not** start Phase 1 implementation yet.

First run a repository-wide Codex analysis against this exact baseline and this document. Codex should challenge the assumptions, identify hidden call paths and compatibility constraints, and revise this plan into an implementation-ready v1.0 with:
- concrete module/file names;
- exact config compatibility rules;
- migration sequence;
- test files to add/modify;
- per-phase PR boundaries;
- dependency graph between phases;
- rollback points;
- explicit non-goals.
