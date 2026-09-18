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

A second major use case is **multi-document aggregation**, where a floating set of source documents must be treated as one logical input and produce one output, for example:

`all news for one day -> deduplicate/cluster/rank -> select Top 10 -> summarize -> one daily briefing`

The target is therefore **not a multidim-only reducer** and not only a single-document reducer. The target is an extensible Reduction Engine that preserves current simple reducers while enabling task-specific, structured, semantic, adaptive hierarchical, and collection-level reduction.

## 2. Core architectural principle

Keep five concerns separate:

1. **Logical Work Unit / Aggregation Scope** — what source members belong to one requested output.
2. **Stage / task orchestration** — what business operation runs next.
3. **Map / slice execution** — how an input is divided and processed in parallel.
4. **Reduction Engine** — how N local outputs become a smaller/global result, potentially over multiple rounds.
5. **Output Profile** — how the final result is normalized/validated/serialized for a sink.

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


### 3.5 Source-agnostic Reduction Core and source-specific runtime boundaries

The **Reduction Engine core must remain source-agnostic**.

Reducer profiles, reduction controllers, worker execution, hierarchical rounds, and reducer results should operate on logical items, payloads, provenance, and execution context. They must not contain source-specific branches such as:

```python
if ctx.mode == "es":
    ...
elif ctx.mode == "sql":
    ...
elif ctx.mode == "txt":
    ...
```

Source-specific responsibilities belong outside the Reduction Core.

Conceptually:

```text
TXT / SQL / ES / other source
        ↓
Source / Collection Adapter
        ↓
Logical Work Unit / Collection Manifest
        ↓
ReductionStage / Reduction Core
        ↓
Final Result
        ↓
Sink / Writeback Adapter
```

#### Row Merger boundary

Existing Row Merger logic is primarily a database-oriented writeback coordination layer for SQL/ES-style records/documents. It must **not** become a required dependency of the Reduction Engine.

The intended direction is:

```text
Reduction Engine
    ↓
final reduced result
    ↓
if SQL/ES sink:
    Row Merger / database writeback coordination

if file/TXT sink:
    file/artifact output path
```

Codex must verify the exact current Row Merger call paths, but the architecture should preserve this boundary unless repository evidence proves otherwise.

#### Support priority by source type

Single-document hierarchical reduction should remain usable across supported input modes, including TXT/file, SQL, and ES.

However, **multi-document Collection Aggregation should be productionized first for database-backed sources**, especially SQL and Elasticsearch, because they naturally provide stable record identity, query/filter semantics, grouping, pagination, and writeback support.

Recommended priority:

1. **SQL / Elasticsearch**
   - first-class Collection Manifest resolution;
   - query/group-based aggregation;
   - retry/resume against stable member identity;
   - aggregate output writeback.

2. **TXT / file sources**
   - keep the Reduction Core usable;
   - support single-document hierarchical reduction fully;
   - optionally support explicit/folder-snapshot collection manifests;
   - do not build a second database-like filesystem job-management system merely to achieve parity with SQL/ES.

This is a prioritization and boundary rule, not a hard architectural exclusion. File-based collection support may grow later if a real use case justifies it.

## 4. Proposed conceptual model

### 4.1 Logical Work Unit, Input Collection, and Collection Manifest

The Reduction Engine should operate on a generic **logical work unit** rather than assume that every job is exactly one source document.

A logical work unit may represent:

- one record;
- one document;
- one document split into many chunks;
- one explicit collection of documents;
- one query-defined collection whose membership is snapshotted at job start;
- one previous stage/reduction output.

The key contract is:

> one logical work unit owns one aggregation scope and produces one logical output for that scope.

This unifies both:

```text
single long document
-> chunks
-> reduction
-> one output
```

and:

```text
N source documents
-> document-level workers
-> cross-document reduction
-> one output
```

#### Collection Manifest

A multi-document aggregation job must not continuously change membership while it is running. A query such as “today's news” may match more documents as new content arrives, so the job should snapshot membership into a stable Collection Manifest before reduction begins.

Candidate manifest information:

```json
{
  "collection_id": "daily-news-2026-09-18",
  "source_kind": "elasticsearch",
  "created_at": "...",
  "query_fingerprint": "...",
  "members": [
    {"id": "doc-a", "version": "..."},
    {"id": "doc-b", "version": "..."}
  ]
}
```

The exact representation must be decided after repository analysis, but the contract should support:

- deterministic retry and resume;
- audit/provenance showing which source members produced the output;
- stable membership across hierarchical rounds;
- optional source version/fingerprint information when available;
- no secret query credentials persisted into manifests.

The initial implementation does **not** require a full new scheduler/job model. A Collection Manifest may be introduced as an input/adaptor contract first, then integrated more deeply with SQL/ES grouping later.

#### Collection formation modes

The architecture should leave room for:

- **explicit collection** — caller supplies a fixed list of members;
- **query collection** — resolve a query once, then snapshot members;
- **grouped collection** — form one work unit per group key such as date/category/customer/report batch.

Examples:

```text
date=2026-09-18
-> 643 news documents
-> one daily-hot-topics work unit
-> one briefing output
```

or:

```text
GROUP BY report_date
-> one collection per date
-> one aggregate output per date
```

Reducer code should consume logical items/provenance, not hard-code that all items came from one file's slice directory.

### 4.2 Reducer Profile

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

### 4.3 Reduction Controller

A Reduction Controller answers:

> Is one reduce pass enough? If not, how should another round be created and when should reduction stop?

Initial controllers:

- `single_pass` — default and legacy-compatible.
- `fixed_rounds` — deterministic N-round operation.
- `adaptive_hierarchical` — continue while deterministic stop criteria are not met.

### 4.4 Reduction Policy

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

### 4.5 Reducer Result

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

### 4.6 ReductionStage and Worker Executor

The architecture should support both of these practical compositions without introducing arbitrary mutual recursion:

1. a normal pipeline stage may internally perform one or many reduction rounds;
2. each chunk processed inside a reduction round may itself require more than one ordinary processing step.

Do **not** model this as unrestricted:

`Stage -> Reducer -> Stage -> Reducer -> ...`

That would turn the Reduction Engine into a general recursive workflow engine and greatly complicate cancellation, retry scope, progress accounting, artifact naming, resume, concurrency budgeting, and cycle detection.

Instead introduce a constrained execution boundary:

```text
ReductionStage
    =
Reduction Controller
+ Worker Executor
+ Reducer Profile
```

The **Worker Executor** answers:

> What work should be performed independently for each chunk in this round?

A worker may be:

- a single existing task/prompt execution;
- a reference to a small existing stage sequence / mini-pipeline.

Conceptually:

```text
Pipeline
  |
  +-- ordinary Stage
  |
  +-- ReductionStage
  |     |
  |     +-- Controller
  |     |     +-- round 1
  |     |     +-- round 2
  |     |     +-- ...
  |     |
  |     +-- Worker Executor
  |     |     +-- Single Task
  |     |     +-- PipelineRef / Mini Pipeline
  |     |
  |     +-- Reducer Profile
  |
  +-- ordinary Stage
```

This gives the useful effect of both “Stage contains reducer” and “reducer contains multiple stages” while keeping a single orchestration direction.

For example, a hierarchical summarization round could execute for each chunk:

```text
summary
-> fact/entity preservation check
-> cleanup
-> chunk result
```

and then reduce all chunk results into the round output.

A later round may choose a different worker pipeline or reducer profile.

#### v1 nesting guard

To keep v1 reviewable and safe:

- a `ReductionStage` worker may execute a single task or an ordinary mini-pipeline;
- arbitrary recursive `ReductionStage -> PipelineRef -> ReductionStage -> ...` nesting is **not** a goal;
- the architecture must carry an explicit reduction-depth / execution-budget context from the beginning;
- the implementation must reject cycles/self-reference;
- the first implementation may default to no nested ReductionStage workers, but the contract should support a **small bounded depth** (for example depth 2) without redesign;
- any enabled nested reduction must share the parent concurrency/model budget rather than opening uncontrolled nested pools.

A real bounded-nesting use case is collection aggregation where each member document may itself be oversized:

```text
Collection ReductionStage
  -> Worker Pipeline per document
       -> bounded document-level hierarchical ReductionStage
  -> document-level compact outputs
  -> collection-level dedup/cluster/rank/top-k reducer
```

Codex must determine whether the existing stage abstractions can serve as the worker executor directly or whether a minimal `Executable` / adapter protocol is needed.

The goal is maximum practical composition with minimum orchestration complexity, not a replacement for a general DAG/workflow engine.

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

Collection-level conceptual example:

```yaml
collection:
  id: daily-news-2026-09-18
  source: elasticsearch
  snapshot_membership: true
  group_by: null

reduction:
  controller: single_pass
  profile: composite
  steps:
    - dedup
    - cluster
    - rank
    - top_k:
        k: 10
    - semantic_llm
```

A grouped source may later form multiple logical work units, for example one collection per date. This syntax is provisional; Phase 0 must first identify the correct source/scheduler integration seam.

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
- SQL/ES/file source enumeration and the safest way to snapshot a multi-document collection;
- existing row/document identity, source version/fingerprint, and grouping semantics;
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

### Phase 4 — Logical Work Unit and Collection Manifest foundation

Goal: support “many source documents -> one logical output” without forcing an immediate rewrite of the scheduler.

Implement/design:
- logical work-unit / aggregation-scope contract;
- stable Collection Manifest;
- explicit fixed-member collections;
- adapter path for query-resolved collections whose membership is snapshotted before execution;
- provenance/member identity contract;
- collection-level input ordering where meaningful;
- deterministic retry/resume against the same manifest.

Initial acceptance case:
- a fixed collection of small documents can be mapped independently and reduced into one output;
- retry uses the same members rather than re-querying a moving source set.

Production priority for Collection Manifest integration is **SQL and Elasticsearch first**. File/TXT support may initially be limited to explicit or folder-snapshotted manifests and must not drive a database-like filesystem scheduler redesign.

Phase 4 does not yet require advanced ranking or a new generalized job scheduler.

### Phase 5 — Composite deterministic reducers

Goal: make reducers reusable building blocks for both single-document and collection-level aggregation.

Candidates:
- `entity_union`;
- exact/canonical dedup helpers;
- configurable list union;
- field-aware scalar policies;
- `group_by`;
- `dedup`;
- `rank`;
- `top_k`;
- `composite` reducer pipeline.

No LLM reducer is required yet.

### Phase 6 — Semantic LLM reducer

Goal: permit a reduction round itself to invoke an LLM for global consolidation.

Requirements:
- reuse existing model/client/parallelism infrastructure rather than create a second LLM stack;
- explicit reducer prompt/task configuration;
- token-budget enforcement;
- audit usage integrated with existing LLM call audit;
- deterministic outer controller remains responsible for stop decisions;
- semantic reducer failure must not silently fall back to unsafe structural merge unless configured.

This phase enables collection-level final synthesis such as a daily Top-10 briefing after deterministic candidate reduction.

### Phase 7 — Structured relational reducer

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

### Phase 8 — Multi-stage integration, ReductionStage, bounded nested reduction, and round-aware workers

Goal: let any stage choose a reduction policy while preserving stage semantics, and allow each reduction round to execute either a single task or an ordinary mini-pipeline per chunk.

Support:
- no reducer;
- one-pass reducer;
- hierarchical reducer inside one `ReductionStage`;
- reducer profile changing by round;
- worker task/prompt changing by round;
- worker `PipelineRef` / mini-pipeline where compatible with existing stage execution;
- reducer output feeding the next explicit business stage;
- bounded nested reduction where a collection member's worker pipeline must first reduce an oversized document.

Critical rules:
- **rounds remain internal to a ReductionStage**;
- existing stage manifests/writeback selectors must not mistake rounds for additional stages;
- the Reduction Engine is not an arbitrary recursive workflow engine;
- cycles/self-reference are invalid;
- nesting depth is explicit and small;
- worker execution and reduction rounds share the existing concurrency/model budget rather than create nested uncontrolled pools.

### Phase 9 — Production hardening and operational visibility

Add:
- metrics for rounds/chunks/tokens/reduction ratio;
- collection member counts and manifest identity in audit/provenance;
- bounded audit logs;
- clear stop reason (`target_reached`, `max_rounds`, `stalled`, `error`);
- failure/retry semantics;
- cancellation behavior;
- cleanup/retention policy for intermediate artifacts;
- concurrency limits for nested map/reduce so hierarchical/collection reduction cannot oversubscribe GPUs/endpoints;
- end-to-end ES/SQL/file regression tests.

## 8. Multidimensional-event problem as acceptance case, not architecture driver

The current multidim failure demonstrates why the engine is needed:
- per-slice `E1` identifiers collide;
- linked `event_ids` become ambiguous;
- article-level scalars conflict;
- generic list concat/deep merge cannot perform semantic event reconciliation.

However, do not solve v1 by placing multidim-specific branches inside generic combine code.

Use it as an acceptance test for Phase 7:
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

## 9.1 Multi-document collection aggregation acceptance case

A second reference scenario should cover:

`all source documents matching one aggregation scope -> one aggregate output`

Example:

```text
today's 643 news documents
-> snapshot Collection Manifest
-> per-document compact analysis
-> dedup / cluster related coverage
-> rank candidate hot topics
-> top_k(10)
-> semantic final synthesis
-> one "daily Top 10 news" output
```

Assertions:
- collection membership is fixed for the run even if new matching documents arrive later;
- retry/resume reuses the same manifest;
- every aggregate output preserves source-member provenance;
- deterministic reducers can shrink the candidate set before any semantic LLM reducer;
- the final Top-K count is a task policy, not hard-coded into the engine;
- a collection member may eventually use bounded document-level hierarchical reduction if the member itself is oversized;
- collection-level and document-level reductions share concurrency and nesting budgets;
- the output profile validates the one final collection result exactly once.

This use case should guide Phase 4-6 design, but it must not force a “news-specific” reducer into the generic engine.

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

### Collection tests
- fixed explicit collection -> one output;
- query collection membership snapshot;
- retry/resume uses identical manifest membership;
- provenance contains all selected member IDs without leaking secrets;
- deterministic dedup/rank/top-k composition;
- bounded document-level reduction inside a collection worker where enabled.

### Integration tests
- legacy single-stage;
- explicit multi-stage;
- SQL/ES row-merger source resolution;
- hierarchical summary;
- multi-document collection aggregation;
- structured relational multidim.

## 11. Safety and failure semantics

- Never weaken an output profile merely to make a reducer result pass.
- Never silently guess semantic conflict resolution in a deterministic reducer.
- Invalid structured output should remain observable.
- Semantic repair/consolidation must be explicit and auditable.
- No infinite hierarchical recursion.
- Nested reduction concurrency must respect existing model/slice parallelism controls.
- Collection membership must be snapshotted before processing; a running job must not silently absorb newly arriving source members.
- Collection manifests must preserve provenance without persisting credentials or secret source configuration.
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
11. Can the existing stage runner/configuration be reused as the Worker Executor for a ReductionStage, or is a minimal executable adapter needed?
12. Which v1 nesting restrictions should be enforced so mini-pipeline workers remain useful without creating a recursive workflow engine?
13. What is the safest source-layer seam for resolving and snapshotting a Collection Manifest across ES, SQL, and file modes?
14. Which source identity/version fields are stable enough to support deterministic collection retry/resume?
15. Should collection outputs write to a new aggregate sink/document identity, or can current writeback abstractions represent one-output-per-group cleanly?
16. Should bounded nested reduction (for oversized documents inside a collection) be enabled in the first collection release or only designed into the execution context for a later PR?
17. Where exactly should SQL/ES Row Merger/writeback coordination sit relative to the source-agnostic Reduction Core, and which current call paths must remain untouched?
18. What is the minimal file/TXT collection adapter worth supporting without recreating database-grade claim/retry/grouping semantics in the filesystem layer?

## 13. Definition of success

The project is successful when:
- existing tasks behave exactly as before unless they explicitly opt into new reduction behavior;
- simple tasks stay simple and cheap;
- advanced tasks can select richer reducers;
- a stage can perform adaptive multi-round reduction;
- a stable collection of multiple documents can be treated as one logical work unit and produce one aggregate output;
- the same Reduction Core works independently of TXT/SQL/ES source mode, while source-specific collection discovery and writeback remain adapters outside the core;
- SQL/ES can receive first-class collection production support without forcing equivalent database-style orchestration onto TXT/file mode;
- multidim/global relational outputs can be reduced without local-ID collisions;
- output profiles remain the final validation boundary;
- multi-stage orchestration remains clear and unchanged in meaning;
- a ReductionStage can use either a single task or an ordinary mini-pipeline as its per-chunk worker without requiring arbitrary Stage/Reducer recursion;
- bounded nested reduction can be introduced without redesign when a collection member itself is oversized;
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
- collection/source membership snapshot design;
- bounded nesting/concurrency-budget design;
- rollback points;
- explicit non-goals.
