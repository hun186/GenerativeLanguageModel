# Reduction Engine v1 — Architecture and Incremental Delivery Plan

> **Implementation status:** Reduction Engine v1 A–L plus the release-audit
> bounded-retention reporting corrective are implemented on `main` as of
> verified merge `91e39503c8e84d17752f9d26a23ff6b34db75b9e`. The blocker
> identified by the closure audit was resolved by PR #201 and passed a fresh
> hosted 24-case gate. PR #200 remains documentation/release closure only and
> requires its own fresh hosted 24-case acceptance before merge. This document
> remains the original architecture/delivery plan; current operator contracts
> are documented in `docs/usage/reduction_engine_v1.md`.

Status: **Implementation-ready v1.0 architecture plan — Phase 0 reconciled**  
Baseline: `c834959d8482e96ab3e815278aec2137952df8d7` (`main`)  
Scope: design only; no production behavior changes in this branch  
Phase 0 reconciliation basis: authoritative PR #177 plan + source-backed Codex review findings

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

### 2.1 Phase 0 source-backed findings now treated as design constraints

Repository inspection confirmed the following points and they are no longer open architectural guesses:

- `combine_api_finished_item()` is the live authoritative slice combiner. Compatibility work must preserve its observed text ordering, one-level JSON-list flattening, conditional audited dict merge, malformed-JSON fallback, and single-slice versus multi-slice envelope behavior.
- legacy TXT execution still uses filesystem-backed TODO/RUNNING/Success artifacts and the live combiner after LLM execution; v1 should integrate around this path rather than redesign it.
- SQL/table processing shares scheduler, registry, Row Merger, and sink/writeback coordination; Elasticsearch reuses this family of runtime paths and adds strict Output Profile validation plus ES persistence.
- `czjLLM/pipeline/merge/` is a disconnected/experimental skeleton relative to the live TXT/SQL/ES runtime. It is not the Reduction Engine foundation and must remain separate unless a later dedicated cleanup proves otherwise.
- current business-stage execution is too stateful to serve directly as the generic reduction worker. Reduction v1 should use a small `Executable` contract with adapters for a single task and a bounded `PipelineRef`.
- existing stage manifests are execution artifacts, not immutable collection identity. Collection Manifest requires a distinct contract with stable membership, fingerprints/versions, ordering, lineage, contract version, and atomic persistence.
- current `n_process`, `nProcess`, slice-level workers, row/document workers, and endpoint concurrency do not form one inherited budget. Shared `ExecutionBudget` is a prerequisite before collection fan-out and semantic/nested reduction.
- existing SQL/ES row/document update identity does not solve aggregate creation idempotency. Collection outputs need a derived stable `aggregate_output_id` (or equivalent) and idempotent sink upsert semantics.

These findings refine the draft without changing its original goals: legacy behavior remains authoritative unless a task explicitly opts into the Reduction Engine.

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

`czjLLM/pipeline/merge/` contains `BaseMergeStrategy` and doc-type-specific strategy skeletons, but Phase 0 source inspection found this package disconnected from the live TXT/SQL/ES runtime and containing placeholder/TODO-oriented paths.

Decision for v1:

- do **not** use `pipeline/merge/` as the Reduction Engine foundation;
- do not silently retrofit or delete it in Reduction Engine PRs;
- keep it separate from the production reduction package;
- if useful logic is discovered later, reuse it only through an explicit adapter or low-level helper after independent verification.

This avoids conflating similarly named but operationally separate “merge” concepts.

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

Phase 0 source inspection confirmed this boundary for the live SQL/table/ES paths: Row Merger remains writeback coordination outside the source-agnostic Reduction Core.

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
- stable ordering metadata where a reducer depends on source order;
- a collection version / parent-manifest relationship so future late-arriving or incremental updates can be represented without redefining the entire model;
- aggregation-window metadata (for example event time vs publish time vs ingest time, timezone, and watermark/cutoff policy) owned by the collection/source layer rather than the reducer;
- no secret query credentials persisted into manifests.

The first release may recompute a collection from a new snapshot rather than perform true incremental aggregation. However, the manifest identity model should not block a future lineage such as:

```text
daily-news v1 -> members through 18:00
daily-news v2 -> parent=v1 + late-arriving members through 23:59
```

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

#### Aggregate-of-aggregates

A collection member does not have to be a raw source document. It may also be a versioned aggregate artifact produced by an earlier pipeline.

This enables higher-level aggregation without a separate architecture:

```text
daily briefings
-> weekly major developments
-> monthly situation summary
-> quarterly report
```

The Reduction Engine should therefore preserve enough artifact identity, provenance, and contract/version metadata for an aggregate result to become a later collection member safely. v1 does not need to implement every multi-level reporting workflow, but the Logical Work Unit contract must not assume members are always raw documents.

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

Phase 0 resolved this question: the existing business-stage abstraction should **not** directly serve as the generic Reduction Worker Executor because it owns stage snapshots, barriers, retry/writeback state, and business-stage identity.

Reduction v1 should instead introduce a small execution contract, conceptually:

```python
class Executable(Protocol):
    def run(self, item, context):
        ...
```

with repository-consistent adapters such as:

- `TaskExecutable` — execute one task/prompt using the existing LLM runtime;
- `PipelineRefExecutable` — execute a bounded ordinary mini-pipeline through existing stage machinery without exposing stage internals to the Reduction Core.

The exact method signature may change during PR B/K implementation, but the dependency direction is fixed: Reduction Core depends on the small executable contract, not on the entire stage runtime.

The goal is maximum practical composition with minimum orchestration complexity, not a replacement for a general DAG/workflow engine.

### 4.7 Cross-cutting execution, identity, quality, and lifecycle contracts

The Reduction Engine introduces workflows where the same logical work unit may span many workers, rounds, retries, and sinks. Several contracts should therefore be designed before implementation even if some advanced capabilities are deferred.

#### Idempotency and aggregate output identity

Retries must not create duplicate aggregate outputs after an ambiguous writeback result.

A stable aggregate identity should be derivable from explicit business scope and versioned execution inputs, for example conceptually:

```text
aggregation scope
+ collection/work-unit identity
+ task/pipeline version
+ reduction config fingerprint
-> aggregate output key
```

The exact formula belongs to Phase 0 design. Do not use unstable runtime values such as PID, temporary path, or wall-clock execution time as the sole identity.

#### Pipeline / prompt / reducer lineage

Final and intermediate aggregate artifacts should be able to record non-secret lineage such as:

- source collection/work-unit version;
- pipeline/task version or configuration fingerprint;
- reducer profile name and reducer-contract version;
- prompt/template fingerprint where relevant;
- model metadata already allowed by current output metadata policy;
- parent aggregate identity for aggregate-of-aggregates.

This should extend or reuse existing metadata mechanisms where possible instead of inventing a parallel provenance system.

#### Partial-failure policy

A collection may contain hundreds or thousands of members and some workers may fail. Whether an aggregate is allowed to continue must be explicit policy rather than reducer guesswork.

Candidate policy concepts:

- `require_all`;
- minimum success ratio;
- minimum success count;
- allowed failure classes;
- `allow_partial_with_warning`.

If a partial collection result is accepted, the final provenance/audit must record that the result was produced from an incomplete member set.

#### Ordering contract

Reducers differ in ordering semantics. Examples:

- translation/text concat requires stable order;
- entity union generally does not;
- ranking intentionally changes order.

Reducer metadata/protocol should be able to declare concepts such as:

- `requires_stable_order`;
- `preserves_order`;
- `reorders_by_policy`.

Source/Collection Adapters must provide stable source ordering when required, rather than relying on incidental SQL/ES/filesystem enumeration order.

#### Shared Execution Budget

Nesting depth alone is not enough to control work. A collection may fan out into documents, each document into slices, and each round into semantic-reducer calls.

The execution tree should inherit a shared budget concept that may cover:

- maximum active LLM calls;
- per-model / per-endpoint concurrency;
- slice workers;
- reduction workers;
- nested reduction depth;
- optional token/cost budget.

Child workers borrow from the parent budget; they must not create independent uncontrolled pools.

#### Intermediate artifact retention and garbage collection

Hierarchical and collection reduction may generate many manifests, round outputs, chunk outputs, and audits.

The architecture should define retention policy concepts such as:

- keep final only;
- keep failed/interrupted artifacts;
- keep all artifacts in debug mode;
- TTL / garbage-collection policy;
- pinned artifacts required for resume or audit.

Use existing atomic I/O primitives where possible.

#### Quality / coverage hook (extension point)

Size convergence is not equivalent to information quality. A 50,000-token source can be reduced below a target while losing required entities, sections, or evidence.

v1 does not need a universal quality scorer, but the controller/result contract should leave an extension point for task-specific metrics such as:

- required-section coverage;
- entity/evidence retention;
- citation/provenance coverage;
- schema completeness;
- task-specific acceptance checks.

Quality checks should be explicit policy/hooks, not hidden heuristics inside generic reducers.

#### Cache / reuse hook (extension point)

Collection aggregation should eventually be able to reuse document-level intermediate results when the source member and worker pipeline have not changed.

A future cache key may combine source fingerprint/version with worker/pipeline configuration fingerprint. v1 does not need to implement a global cache, but worker/result contracts should not require recomputation by design.

#### Reducer / schema contract versioning (extension point)

Structured reducers and their intermediate artifacts will evolve. Reducer profiles should have an explicit contract/version concept so incompatible old intermediate artifacts can be rejected or migrated rather than silently consumed by newer code.


### 4.8 Concrete package ownership for v1

The implementation should converge on a focused source-agnostic package:

```text
czjLLM/reduction/
  contracts.py
  config.py
  registry.py
  engine.py
  controllers.py
  policies.py
  execution_budget.py
  artifacts.py
  executables.py
  work_units.py
  manifests.py
  reducers/
    legacy.py
    deterministic.py
    semantic.py
    relational.py
  adapters/
    collections_sql.py
    collections_es.py
    collections_files.py
    output_profiles.py
    writeback.py
```

Exact file splitting may be compressed if implementation proves some modules too small, but ownership boundaries should remain:

- core contracts/controllers/reducers contain no SQL/ES/TXT branching;
- collection adapters own source-specific membership resolution;
- Output Profile integration remains an adapter/final validation boundary;
- Row Merger/writeback integration remains outside the reducer implementations;
- `combine_utils.py`, `slice_merge.py`, the live prompt-pipeline controller, and Row Merger remain compatibility facades during migration;
- `pipeline/merge/` remains outside this package.

### 4.9 Minimal implementation contracts

The first implementation PRs should converge on small contracts equivalent to:

```python
class Reducer(Protocol):
    profile: str
    contract_version: str
    requires_stable_order: bool
    preserves_order: bool

    def reduce(self, items, context) -> ReducerResult: ...

@dataclass
class ReducerResult:
    payload: object
    profile: str
    contract_version: str
    warnings: list[str]
    provenance: dict
    metrics: dict

class ReductionController(Protocol):
    def next_action(self, result, context) -> str: ...

class Executable(Protocol):
    def run(self, item, context): ...

@dataclass(frozen=True)
class CollectionManifest:
    collection_id: str
    collection_version: str
    contract_version: str
    source_kind: str
    members: tuple
    scope_fingerprint: str
    ordering: object | None
    window: object | None
    parent_manifest_id: str | None

class ExecutionBudget(Protocol):
    def acquire(self, resource_kind, amount=1): ...
    def release(self, lease): ...
```

Additional planned contracts include `LogicalWorkUnit`, `CollectionMember`, `ReductionPolicy`, `ReductionContext`, `ReductionStage`, `TaskExecutable`, `PipelineRefExecutable`, and artifact/checkpoint identity.

These are architectural contracts, not implemented APIs. PR B must finalize exact Python typing against repository conventions before any routing changes.

## 5. Configuration direction

Do not break existing configuration.

If no new reduction config is present, existing behavior must remain unchanged. `reduction.enabled: false` should likewise preserve the legacy path.

Phase 0 also resolves these validation rules:

- explicit new Reduction Engine routing is opt-in; never infer it from task shape;
- legacy `merge_slices` remains authoritative for legacy tasks;
- a configuration that simultaneously requests legacy `merge_slices` semantics and an incompatible explicit `reduction` profile must fail validation rather than silently reconcile the two;
- self-referential/cyclic `PipelineRef` is invalid;
- v1 nesting depth is explicitly bounded (target maximum depth 2 unless implementation evidence requires a stricter first release);
- child executors may not create independent concurrency pools outside the inherited `ExecutionBudget`;
- query/group collections require deterministic member identity and ordering whenever the selected reducer declares stable-order requirements;
- stale reducer/schema contract versions are invalid for resume/cache reuse unless an explicit compatible migration exists.

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

A grouped source may later form multiple logical work units, for example one collection per date. The YAML above is intentionally illustrative: PR C owns the exact reduction config parser/validation shape, and PR F/G own the exact collection/source fields after binding them to the live scheduler and source adapters.

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

### Phase 0 — Repository-wide architecture inventory and contract freeze — **COMPLETE**

No production changes.

Phase 0 source inspection established the live combine/writeback boundaries, separated experimental `pipeline/merge/` from the production runtime, confirmed the Row Merger and Output Profile boundaries, identified the need for a small `Executable` worker contract, promoted shared `ExecutionBudget` ahead of fan-out, and required immutable Collection Manifest plus aggregate-output idempotency.

The remaining configuration and API details are intentionally assigned to their owning implementation PRs rather than left as architecture-review blockers.

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

### Phase 4 — Shared Execution Budget

Goal: establish one inherited concurrency/resource budget before collection fan-out or nested semantic work is introduced.

Implement/design:
- shared lease/token budget across row/document workers, prompt slices, reduction workers, nested ReductionStages, and semantic reducer calls;
- adapters from current `n_process` / `nProcess` / `slice_parallelism` / endpoint scheduling into one parent budget;
- child execution borrows capacity from the parent instead of creating independent pools;
- explicit nesting-depth accounting;
- cancellation-safe lease release;
- diagnostics showing requested versus granted concurrency.

Exit criteria:
- no collection or nested reducer can multiply existing worker pools without going through the shared budget;
- legacy tasks with no reduction config preserve existing effective parallelism.

### Phase 5 — Logical Work Unit and Collection Manifest foundation

Goal: support “many source documents -> one logical output” without forcing an immediate rewrite of the scheduler.

Implement/design:
- logical work-unit / aggregation-scope contract;
- stable Collection Manifest;
- explicit fixed-member collections;
- adapter path for query-resolved collections whose membership is snapshotted before execution;
- provenance/member identity contract;
- collection-level input ordering where meaningful;
- deterministic retry/resume against the same manifest;
- collection version / parent-manifest lineage;
- aggregation-window/timezone/watermark semantics;
- stable ordering when required;
- idempotent aggregate-output identity contract.

Initial acceptance case:
- a fixed collection of small documents can be mapped independently and reduced into one output;
- retry uses the same members rather than re-querying a moving source set.

Production priority for Collection Manifest integration is **SQL and Elasticsearch first**. File/TXT support may initially be limited to explicit or folder-snapshotted manifests and must not drive a database-like filesystem scheduler redesign.

Phase 4 does not yet require advanced ranking or a new generalized job scheduler.

### Phase 6 — Composite deterministic reducers

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

### Phase 7 — Semantic LLM reducer

Goal: permit a reduction round itself to invoke an LLM for global consolidation.

Requirements:
- reuse existing model/client/parallelism infrastructure rather than create a second LLM stack;
- explicit reducer prompt/task configuration;
- token-budget enforcement;
- audit usage integrated with existing LLM call audit;
- deterministic outer controller remains responsible for stop decisions;
- semantic reducer failure must not silently fall back to unsafe structural merge unless configured.

This phase enables collection-level final synthesis such as a daily Top-10 briefing after deterministic candidate reduction.

### Phase 8 — Structured relational reducer

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

### Phase 9 — Multi-stage integration, ReductionStage, bounded nested reduction, and round-aware workers

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

### Phase 10 — Production hardening and operational visibility

Add:
- metrics for rounds/chunks/tokens/reduction ratio;
- collection member counts and manifest identity in audit/provenance;
- bounded audit logs;
- clear stop reason (`target_reached`, `max_rounds`, `stalled`, `error`);
- failure/retry and partial-success semantics;
- idempotent aggregate writeback behavior;
- cancellation behavior;
- cleanup/retention/GC policy for intermediate artifacts;
- shared execution-budget enforcement across document, slice, reduction, and nested workers;
- optional cache/reuse integration for unchanged member-level results;
- lineage/version metadata and aggregate-of-aggregates provenance;
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
- aggregation-window/timezone/watermark semantics are explicit;
- retry/resume reuses the same manifest and aggregate identity;
- a later snapshot can form a versioned successor collection without mutating the already-running manifest;
- every aggregate output preserves source-member provenance;
- deterministic reducers can shrink the candidate set before any semantic LLM reducer;
- the final Top-K count is a task policy, not hard-coded into the engine;
- partial member failures follow explicit policy and are visible in provenance;
- source ordering is deterministic when the selected worker/reducer requires it;
- a collection member may eventually use bounded document-level hierarchical reduction if the member itself is oversized;
- collection-level and document-level reductions share concurrency and nesting budgets;
- the output profile validates the one final collection result exactly once.

This use case should guide Phase 5-7 design, but it must not force a “news-specific” reducer into the generic engine.

## 9.2 Implementation PR roadmap after this plan merges

Phase 0 remains documentation-only. The implementation sequence should be split into small PRs with explicit rollback boundaries:

1. **PR A — Characterization / Golden Tests**  
   Production behavior change: **NO**. Freeze current combine, malformed/empty handling, single-vs-multi-slice envelopes, stage-source writeback, Row Merger, and Output Profile behavior before routing changes.
2. **PR B — Contracts, Reducer Registry, and legacy adapters**  
   Introduce source-agnostic contracts and wrap existing concat/list/deep-merge behavior without changing defaults.
3. **PR C — Strict configuration and opt-in single-pass routing**  
   Add explicit `reduction` parsing/validation; no-config tasks remain on the legacy path.
4. **PR D — Hierarchical Controller and atomic checkpoints**  
   Add deterministic multi-round text reduction, stop guards, restartable round artifacts, and metrics.
5. **PR E — Shared Execution Budget**  
   Unify inherited concurrency limits before collection fan-out, semantic reducer fan-out, or bounded nested reduction.
6. **PR F — Logical Work Unit and immutable Collection Manifest**  
   Add stable collection identity, member snapshots, ordering/window metadata, lineage, and contract versioning.
7. **PR G — SQL/ES Collection Adapters and idempotent aggregate upsert**  
   Productionize query/group collections for database-backed sources and introduce stable `aggregate_output_id` (or equivalent).
8. **PR H — Deterministic composite reducers**  
   Add reusable dedup/group/union/rank/top-k building blocks.
9. **PR I — Semantic reducer**  
   Reuse existing model/client/audit infrastructure under the inherited ExecutionBudget.
10. **PR J — Structured relational reducer**  
    Add local namespaces, reference remapping, integrity checks, provenance, and canonical ID assignment.
11. **PR K — ReductionStage and bounded PipelineRef nesting**  
    Add Task/PipelineRef executables and explicitly bounded nested reduction using shared budget/depth/cycle checks.
12. **PR L — Retention, GC, cache/reuse integration points, and production hardening**  
    Finalize operational retention, observability, cancellation, audit bounding, and end-to-end source/sink coverage.

**Characterization / Golden Tests remains the mandatory first implementation PR.** No production refactor should precede PR A because current combine/writeback ownership crosses multiple live runtime surfaces.

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
- collection version / parent-manifest lineage;
- aggregation-window/timezone/watermark boundary behavior;
- retry/resume uses identical manifest membership and aggregate identity;
- idempotent writeback after ambiguous/retried completion;
- full-success vs allowed-partial vs rejected-partial policy;
- stable ordering when required by reducer contract;
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
- Aggregation-window/timezone semantics must be explicit for time-based collections; reducers must not silently redefine source membership.
- Partial-success output must be explicit and auditable.
- Aggregate writeback must be idempotent enough that retry cannot silently create duplicate logical outputs.
- Intermediate artifacts must use existing atomic I/O utilities where possible and follow bounded retention/GC policy.
- Secrets/endpoints must not be persisted in reducer audits or project memory.

## 12. Implementation questions by owning PR

Phase 0 is complete. The following questions are deliberately deferred to the implementation PR that owns the relevant contract; they are **not architecture-plan merge blockers** unless implementation proves a contradiction with the boundaries above.

### PR A — compatibility characterization
- Which externally relied-on JSON-list/single-slice/malformed/empty behaviors require golden fixtures beyond the cases already enumerated?
- Which duplicated combine/writeback invocation surfaces need independent characterization?

### PR B/C — contracts, registry, and opt-in config
- What is the smallest integration facade around `combine_api_finished_item()` that preserves legacy imports while enabling explicit reduction routing?
- How should reducer plugin loading mirror Output Profile plugin conventions without creating circular dependencies?
- What exact YAML/ctx names and validation errors best match existing configuration conventions?

### PR D/E — hierarchical controller and ExecutionBudget
- Which existing token/context utility should be authoritative for adaptive stop decisions when a worker mini-pipeline changes models?
- How should cancellation interact with in-flight synchronous HTTP calls?
- How should current `n_process`, `nProcess`, slice parallelism, row/document workers, and endpoint scheduling project into the shared budget?
- Which round artifacts are mandatory checkpoints versus disposable intermediates?

### PR F/G — Logical Work Unit, Collection Manifest, and SQL/ES productionization
- Which SQL and ES identity/version fields are stable enough for deterministic snapshot/retry semantics?
- What exact half-open window/timezone/watermark fields should each source adapter expose?
- What destination table/index/document shape should first-class aggregate outputs use?
- What uniqueness/upsert mechanism should implement the stable `aggregate_output_id`?
- What is the smallest useful TXT/file collection adapter without recreating database-grade claim/retry/grouping semantics?

### PR H/I/J — deterministic, semantic, and relational reducers
- What deterministic clustering/ranking primitives should ship first?
- Should semantic reducer prompts reuse Task declarations, reducer-specific declarations, or both via adapters?
- What minimal generic identifier/reference mapping supports structured relational reduction without becoming a graph framework?
- What quality/coverage metrics are useful as optional hooks without becoming a generic evaluation platform?

### PR K/L — bounded PipelineRef nesting and operations
- Whether bounded nested reduction is enabled immediately or only after the non-nested `PipelineRef` path is proven.
- What operational retention/TTL defaults are required for resume, audit, troubleshooting, and GC?
- What member-result cache/reuse policy is worthwhile after source/reducer contract fingerprints are stable?
- What reducer/schema compatibility policy is needed before reusing old intermediate artifacts?
- What lineage fields are mandatory when aggregate outputs become members of daily→weekly→monthly→quarterly collections?

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
- retries/resume do not create duplicate logical aggregate outputs;
- time-window collections have explicit window/timezone/watermark semantics;
- partial collection results, when allowed, are explicitly marked and auditable;
- aggregate artifacts can become versioned inputs to higher-level aggregation without losing provenance;
- execution budgets and artifact-retention policies prevent nested workloads from growing without bound;
- quality, cache/reuse, and reducer/schema-version hooks can be added without redesigning the core interfaces;
- new reducers can be added through a registry/plugin contract rather than by editing a central `if task == ...` block.

## 14. Recommended immediate next action

Phase 0 repository-wide architecture analysis is now reconciled into this authoritative PR #177 plan.

After this documentation PR is reviewed and merged, begin **PR A — Characterization / Golden Tests** with **no production behavior change**.

Do not begin Reduction Engine routing, collection fan-out, semantic reduction, or structured relational implementation before those golden tests freeze the current live contracts.

The remaining open questions in Section 12 are implementation-detail decisions to resolve in their owning PRs; they are not blockers to merging this architecture plan unless review identifies a contradiction with current source behavior.
