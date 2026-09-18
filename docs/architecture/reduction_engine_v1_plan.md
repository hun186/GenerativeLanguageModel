# czjLLM Reduction Engine v1.0 — Implementation-Ready Architecture Plan

**Status:** Phase 0 design; no runtime implementation exists.
**Production baseline reviewed:** `main@c834959d8482e96ab3e815278aec2137952df8d7`.
**Design branch:** `plan/reduction-engine-v1`.
**Intended predecessor:** plan commit `eaaf89e131ed814dddc6813beb8d3839fc47b587` (not present in the supplied clone; this v2 plan was reconstructed against the authoritative production baseline).
**Compatibility rule:** absence of a `reduction` block means byte/shape-compatible legacy routing, not an inferred reducer.

## 1. Decision summary

1. Add a source-agnostic `czjLLM/reduction/` package. Keep `utilities.combine_utils` as the legacy compatibility facade and adapter target.
2. Do not reuse `czjLLM/pipeline/merge/` as the engine. That package is a disconnected skeleton with placeholder strategies and TODO-based steps; it is neither the live prompt-pipeline merge path nor production-ready. A later one-way adapter may implement the small reducer protocol, but the two abstractions remain separate.
3. Keep business `StageDefinition` and reduction rounds distinct. A `ReductionStage` is invoked within a stage boundary and owns internal round identifiers.
4. Use a minimal `Executable` protocol with adapters for an existing Task and a bounded `PipelineRef`; the current stage runtime cannot directly serve because it owns per-chunk stage state, snapshots, barriers, and retry behavior rather than a single `execute(input, context)` contract.
5. Keep Output Profiles as the strict final sink boundary. Reducer Profiles combine N values; Output Profiles transform/validate one final value. No reducer may weaken profile validation.
6. Keep Row Merger outside the core. It is the live SQL/table/ES coordination and writeback boundary; TXT writes files directly. Reduction returns a result/artifact to the existing sink path.
7. Productionize single-document hierarchical reduction for TXT/SQL/ES before collection execution. Productionize collections first through SQL and ES source/sink adapters; filesystem supports explicit/folder snapshots only.
8. Make manifests immutable, content-addressed, secret-free, and atomically written. A late arrival creates a successor version; v1 recomputes the collection while retaining future delta/reuse keys.
9. Route all nested work through one inherited `ExecutionBudget`. Existing `n_process`/legacy `nProcess`, row-worker and slice-worker values are inputs to the root budget, never licenses to create child pools.
10. Preserve simple deterministic behavior: text concatenation, JSON-list concatenation, and audited deep-dict merge do not invoke an LLM.
11. Version reducer and schema contracts and reject stale artifacts rather than silently consuming them.
12. The first implementation PR remains **Characterization / Golden Tests**, with no production behavior change.

## 2. Source-backed current-state review

### 2.1 Live combine semantics

`combine_api_finished_item()` is the authoritative filesystem combiner. It sorts `Success` paths, ignores empty files and outputs beginning with the converted “no relevant content” marker, and decides JSON mode from prompt text heuristics—not from an explicit output type.

| Case | Observed behavior at baseline | Compatibility consequence |
|---|---|---|
| Text task | Non-empty Success text is concatenated in sorted path order; each fragment is newline-terminated. | `legacy_concat_text` must preserve exact ordering/newline behavior. |
| JSON dict | Dict becomes one element in `json_rows`. | With merge off or one JSON-bearing slice, output is a JSON list. |
| JSON list | Only dict elements are retained and flattened one level into `json_rows`; non-dict elements are discarded. | Characterize before refactoring; do not “improve” silently. |
| `merge_slices=false` | All collected dict rows are serialized as one JSON list. | Default remains this path when the flag is false. |
| `merge_slices=true` | Only when more than one JSON-bearing slice exists, `merge_dict_slices_audited()` returns one dict. Lists concatenate/deduplicate; dicts recurse; scalar conflicts follow configured policy (default `prefer_left`). | Adapter name: `legacy_json_deep_merge`; exact report and shape remain. |
| One slice | The deep merge condition is false; a dict/list response serializes as a list of dict rows. | Do not normalize single-slice shape in compatibility mode. |
| Malformed JSON | Parse error also appends original text; if no valid JSON row survives, text is concatenated. In explicit multistage it logs a warning that stage output may be used. | Preserve fallback and warning behavior in legacy route. |
| Mixed valid/malformed JSON | Valid dict rows win the JSON branch; malformed text chunks are not included in final JSON. | Must be golden-tested as an observed edge case. |
| Empty outputs | Empty fragments are skipped; JSON mode with no content yields `[]`; text mode yields empty text. | Preserve exactly. |
| Ordering | `OSWALK()` output is explicitly sorted before combine. | Stable lexical artifact order is part of concat compatibility. |

`should_merge_slices()` accepts `ctx.merge_slices`, `enable_slice_merge`, or `merge_strategy` values `dict_deep`, `slice_merge`, and `on`. The new parser must preserve those aliases only on the legacy route. `combine_utils.py` also re-exports JSON and slice helpers and is an established compatibility facade.

### 2.2 Actual runtime maps

#### Legacy single-stage TXT, including multi-slice

```text
handle_txt_mode
  -> handle_single_input_file
  -> process_file_to_prompt / TokenizerWrapper
  -> WorkPool/.../<item>/TODO/*.txt                [slice artifacts]
  -> process_prompt_and_merge (no explicit stages)
  -> call_llm_api twice (retry then non-retry)
  -> PromptAPIPipeline.proc / model client
  -> RUNNING -> Success/*.txt                      [local outputs]
  -> combine_api_finished_item                     [CURRENT REDUCTION]
       text: sorted newline concat
       JSON: list flatten/concat
       merge_slices + >1 JSON slice: audited deep dict merge
  -> atomic combined result under finished root
  -> source moved to backup
```

A single slice follows the same path. It is not passed through audited deep merge even when `merge_slices=true`.

#### SQL and table

```text
handle_data_mode Backend(SQL/table)
  -> adapter resolves pending rows
  -> shared sql_mode.runtime.orchestrator.run_pipeline
  -> producer -> schedule_one_row
  -> per-row context + temporary TXT
  -> handle_single_input_file(defer_merge=True)
  -> Registry(item_dir, pk, temp path, expected combined path)
  -> legacy consumer: TODO -> RUNNING -> Success
  -> row_merger_watchdog_generic
       waits for all slices / locates or invokes combine_api_finished_item
       resolve_writeback_payload(combined or stage manifest)
       optional authoritative deep-dict write-map adjustment
       optional JSON flatten/column expansion
  -> SqlSink / ExcelSink / CSVSink
  -> registry/meter/running-state cleanup
```

The orchestrator has an additional end-of-run `run_merge_for()` pass when `MERGE_SLICES` is enabled, but Row Merger remains the write authority. This duplicate invocation surface is a compatibility risk to freeze before routing changes.

#### Elasticsearch

```text
handle_data_mode Backend(ES)
  -> ElasticsearchAdapter resolves a stable-at-read pending stream (not a collection snapshot)
  -> same sql_mode.runtime.orchestrator / producer / scheduler
  -> same prompt artifacts and Row Merger
  -> resolve_writeback_payload
  -> ESSink.write_main / write_flatten
       Output Profile resolution + transform/validation
       metadata construction/redaction
       buffered bulk update by ES _id/business id
  -> final pending recheck
```

ES reuses the SQL/table runtime; it does not have a separate reduction engine. The adapter's query/scroll identity facilities are the future collection seam.

#### Explicit multi-stage (TXT, SQL, table, ES)

```text
normalized ctx.stages -> StageDefinition[]
  -> process_prompt_and_merge_multistage
  -> ChunkStageRuntime per prompt item
  -> run_stage_pipeline rounds over BUSINESS stages
       plan ready stage jobs
       prepare stage TODO from original/previous/named snapshot
       call_llm_api (retry + non-retry)
       barrier: TODO exhausted
       persist item/_stage_outputs/<stage> snapshots
  -> concatenate selected stage snapshots to
       finished/_stage_merges/<source>/<stage>.txt  [CURRENT STAGE COMBINE]
  -> write manifest.json (source, generated_at, stages)
  -> optionally final combine_api_finished_item
  -> SQL/table/ES Row Merger selects combined or `stage:<name>`
  -> sink
```

SQL/table/ES scheduling calls this synchronously per row/document when explicit stage flow is enabled, then marks the registry item ready for writeback. Stage merges currently use plain `"\n".join(parts)`; they are not `pipeline/merge` strategies.

#### Output Profile path

```text
Row Merger write_map
  -> sink.write_main
  -> ESSink resolves per-rule or global profile (`auto` may infer by output column)
  -> OutputProfileRegistry (canonical names + aliases + dynamic plugins)
  -> transformer/validator
       deterministic TypeError/ValueError -> OutputProfileValidationError
  -> serialization/buffered ES write
```

Profiles `none/json/text` pass through; `multidim_event` validates/transforms its domain payload. SQL/table sinks do not provide the same generic registry boundary today; configuration still travels through shared Row Merger and ES-specific serialization helpers in places. V1 must define sink-neutral final validation invocation before claiming uniform profile support.

#### Row Merger/writeback boundary

```text
combined or stage artifact
  -> resolve_writeback_payload
  -> Row Merger: source selection, merge-aware envelope, flatten/expand, retry classification
  -> sink adapter: SQL/table/ES identity and persistence
```

Confirmed: Row Merger is database/tabular orchestration, not a prerequisite for TXT or generic reduction. Keep it downstream. Existing idempotency is update-oriented when a stable row primary key/ES document id already exists; there is no aggregate-output identity for creating a new logical aggregate. Collection writeback must extend sink upsert identity, not embed sink code in reducers.

### 2.3 Separate, experimental, and legacy paths

- `czjLLM/pipeline/` is callable through `run_pipeline()`, but its classification and extraction steps explicitly contain TODO/placeholder behavior and every merge strategy returns a “Skeleton ... merge result.” No live TXT/SQL/ES entry path calls it. Treat it as experimental/separate and never as evidence of production merge semantics.
- `prompt_pipeline` is the active LLM/slice/multistage runtime. Its stage runtime is real but is tightly coupled to filesystem queues and snapshots.
- Functions suffixed `_OLD_1027`, `_0717`, and commented historical blocks are compatibility/dead history, not architecture extension seams.
- `combine_utils.py` is intentionally a compatibility facade; focused implementations already live in `json_combining.py` and `slice_merge.py`.
- Stage manifests are execution artifacts but lack immutable manifest identity, fingerprints, contract versions, parent lineage, or atomic writing. They are not Collection Manifests.
- Pending-running console state is short-lived coordination, not durable resume history.

### 2.4 Runtime state, retry, cancellation, artifacts

- Legacy queue state is directory-based `TODO/RUNNING/Success`; restart recovers RUNNING to TODO and retains Success depending on `resume_policy` (`resume`, `smart_reset`, `full_restart`).
- SQL/table/ES add an in-memory/shared Registry, meter JSON, producer/consumer/merger threads, watchdogs, source running claims, and authoritative post-writeback pending recheck.
- Multistage resume can retain Success, clear `_stage_outputs`, or restart. Its manifest is generated after stage execution and is selected by path/mtime heuristics.
- Cancellation is based on stop events and teardown boundaries, not a durable cancellation record propagated through a nested execution tree.
- `utilities.atomic_io` / safe atomic filesystem helpers are reusable, but several stage snapshots/manifests currently use direct writes. New reduction artifacts must use atomic writes from their first implementation.
- There is no durable multi-round checkpoint schema or artifact GC policy today.

### 2.5 Parallelism and context limits

Current parallel controls are fragmented:

- root/model: model profile `n_process` or legacy `nProcess`, otherwise endpoint-derived `ctx.n_process`;
- row/document: producer multistage worker setting, otherwise `ctx.n_process`/endpoint pool;
- prompt slices: `multistage_slice_parallelism`, `llm_slice_parallelism`, `slice_parallelism`, model-profile values, then `ctx.n_process`;
- legacy LLM rounds: multiprocessing (with targeted Windows thread fallback);
- model endpoint list is used as scheduling capacity but does not establish a global semaphore.

Therefore nested reduction cannot safely compose existing integer settings. `ExecutionBudget` must be a shared lease/semaphore object created once per top-level run. Configuration values cap classes of leases but child executors do not instantiate their own pools.

Authoritative size/context sources are `TokenizerWrapper` for splitting and `utilities.llm_call_audit.resolve_context_limit()` for actual context metadata. The latter prioritizes response/active Ollama context and explicit model config; model names must never be parsed. LLM calls already emit usage/audit rows. Reduction metrics should use an injected `SizeEstimator` backed by the selected tokenizer, falling back to characters only when declared in metrics.

## 3. Target boundaries and responsibilities

| Subsystem | Current responsibility | v1 responsibility/change | Risk |
|---|---|---|---|
| Source adapter | Read TXT, SQL rows, or ES docs; source-specific pending policy. | Resolve members and immutable source references; collection query/group/window semantics remain here. | High: ordering/window drift. |
| Splitter | Tokenizer-driven source slicing into prompt files. | Implement `Chunker` adapter usable for original and prior-round output; no source branches. | Medium: sizing parity. |
| Prompt pipeline | Queue artifacts, LLM calls, business stages. | Remains owner of map execution; exposed through `TaskExecutable`. | High: retry and pool coupling. |
| Success artifacts | Local slice outputs and restart evidence. | Legacy unchanged; reduction adapters wrap values plus provenance. | Medium: stale reuse. |
| `combine_utils` | Live filesystem combine and compatibility exports. | Frozen facade; legacy reducer adapters call existing functions/helpers. | Highest. |
| `slice_merge` | Audited structural dict merge and aliases. | Remains implementation behind `legacy_json_deep_merge`. | High: output shape. |
| `pipeline/merge` | Experimental doc-type skeleton strategies. | Remains separate; optional future `Reducer` adapters only after real implementation. | High if conflated. |
| Logical Work Unit | Absent; one file/row/doc is implicit work. | Stable scope yielding exactly one logical result. | Medium. |
| Collection Manifest | Absent; stage manifest is insufficient. | Immutable member snapshot, lineage, ordering, window, fingerprints. | High. |
| Reduction Engine | Absent. | Orchestrates controller/executable/reducer without source/sink branches. | Medium. |
| ReductionStage | Absent. | One business-stage operation containing internal rounds; bounded nesting. | High: identity confusion. |
| Worker Executor | Stage-specific filesystem runner. | Small `Executable` protocol with Task and PipelineRef adapters. | High. |
| Controller | No adaptive controller. | Deterministic round planning, measuring, stop/failure state. | Medium. |
| Reducer Profile | Implicit combine flags/helpers. | Named/versioned reducer with declared ordering/contracts. | Medium. |
| Multi-stage scheduler | Business-stage dependency/barrier/snapshots. | Invokes ReductionStage as one stage; never exposes rounds as stages. | High. |
| Output Profile | ES registry transformer/validator at sink boundary. | Remains strict final normalization/validation; move invocation behind sink-neutral adapter only if needed. | High. |
| Row Merger | SQL/table/ES combine discovery, source selection, flatten, retries, writes. | Consumes final reduction artifact; performs writeback coordination only. | Highest. |
| Sink/writeback adapter | SQL/table/ES/file persistence. | Adds aggregate idempotency/upsert contract and lineage persistence. | High. |

## 4. Concrete package layout

```text
czjLLM/reduction/
  __init__.py
  contracts.py              # IDs, contracts, ReducerInput/Result, context, metrics
  config.py                 # strict opt-in parser, aliases, validation/fingerprints
  registry.py               # reducer registry and plugin loader
  engine.py                 # source-agnostic round loop
  controllers.py            # single_pass, fixed_rounds, adaptive_hierarchical
  policies.py               # partial failure, stop/quality, retention declarations
  chunking.py               # fan-in plans + tokenizer-backed size adapter
  execution.py              # Executable protocol, task/pipeline adapters
  budget.py                 # inherited lease-based ExecutionBudget
  artifacts.py              # atomic checkpoints, lineage, retention markers
  reducers/
    legacy.py               # adapters over existing concat/deep-merge semantics
    deterministic.py        # later composite/dedup/rank/top_k reducers
    semantic.py             # later TaskExecutable-backed semantic reducer
    relational.py           # later generic ID/reference reducer
  collections/
    contracts.py            # LogicalWorkUnit, CollectionManifest, member/window models
    identity.py             # canonical serialization and fingerprints
    lifecycle.py            # resolve/snapshot/execute/reduce lifecycle
    adapters/
      sql.py
      elasticsearch.py
      filesystem.py         # explicit/folder snapshot only
  integration/
    prompt_pipeline.py      # existing Task/Stage adapter
    output_profiles.py      # final validation bridge
    writeback.py            # Row Merger/sink handoff + aggregate identity
```

Compatibility facades that remain:

- `czjLLM/utilities/combine_utils.py` keeps all public imports and current routing.
- `czjLLM/utilities/slice_merge.py` remains the deep-merge implementation.
- `czjLLM/prompt_pipeline/pipeline_controller.py` remains the active public orchestration entry while opt-in calls delegate to `reduction.integration.prompt_pipeline`.
- `czjLLM/sql_mode/runtime/row_merger_generic.py` remains writeback coordination; it does not become a reducer.
- `czjLLM/pipeline/merge/` remains separate and is not re-exported from `reduction`.

## 5. Minimal Python contracts (design, not implementation)

```python
@dataclass(frozen=True)
class ContractRef:
    name: str
    version: str
    schema_fingerprint: str | None = None

@dataclass(frozen=True)
class ReductionItem:
    item_id: str
    value: object
    ordinal: int | None
    provenance: "Provenance"
    contract: ContractRef

@dataclass(frozen=True)
class ReducerResult:
    value: object
    contract: ContractRef
    metrics: Mapping[str, int | float | str | bool]
    warnings: tuple[str, ...]
    provenance: "Provenance"
    partial: bool = False

class Reducer(Protocol):
    profile: str
    contract_version: str
    ordering: Literal["requires_stable", "preserves", "irrelevant", "reorders"]
    def reduce(self, items: Sequence[ReductionItem], ctx: "ReductionContext") -> ReducerResult: ...

class ReducerRegistry:
    def register(self, name: str, factory: Callable[..., Reducer], *, aliases: Iterable[str] = ()) -> None: ...
    def create(self, name: str, config: Mapping[str, object]) -> Reducer: ...

class Executable(Protocol):
    executable_id: str
    contract_version: str
    def execute(self, item: ReductionItem, ctx: "ReductionContext") -> ReductionItem: ...

@dataclass(frozen=True)
class ReductionPolicy:
    partial_failure: "PartialFailurePolicy"
    retention: "RetentionPolicy"
    on_empty: Literal["finish", "fail"]
    on_stall: Literal["fail", "return_partial"]
    on_max_rounds: Literal["fail", "return_partial"]

@dataclass
class ReductionContext:
    execution_id: str
    work_unit_id: str
    stage_id: str
    round_id: str
    depth: int
    ancestor_executables: tuple[str, ...]
    budget: "ExecutionBudget"
    artifact_store: "ArtifactStore"
    cancellation: "CancellationToken"
    size_estimator: "SizeEstimator"
    lineage: "Provenance"
    policy: ReductionPolicy

class ReductionController(Protocol):
    controller_type: str
    def prepare(self, items: Sequence[ReductionItem], ctx: ReductionContext) -> "RoundPlan": ...
    def decide(self, result: ReducerResult, metrics: "RoundMetrics", ctx: ReductionContext) -> "Decision": ...

@dataclass(frozen=True)
class ReductionStage:
    stage_id: str
    controller: "ControllerConfig"
    worker: "ExecutableRef | None"
    reducer: "ReducerRef"
    input_contract: ContractRef
    output_contract: ContractRef
```

Collection and execution contracts:

```python
@dataclass(frozen=True)
class SourceMemberRef:
    member_id: str
    source_kind: str
    version: str | None
    fingerprint: str | None
    ordinal: int | None
    locator: Mapping[str, str]       # non-secret logical locator only
    aggregate_identity: str | None  # set when member is a prior aggregate

@dataclass(frozen=True)
class AggregationWindow:
    time_field: str
    time_basis: Literal["event", "publish", "ingest", "update"]
    start: str
    end: str
    timezone: str
    cutoff: str
    watermark: str | None

@dataclass(frozen=True)
class CollectionManifest:
    manifest_schema_version: str
    collection_id: str
    collection_version: int
    manifest_id: str                # hash of canonical secret-free body
    parent_manifest_id: str | None
    source_kind: str
    query_fingerprint: str | None
    ordering_key: str | None
    window: AggregationWindow | None
    members: tuple[SourceMemberRef, ...]
    created_at: str

@dataclass(frozen=True)
class LogicalWorkUnit:
    work_unit_id: str
    scope_kind: Literal["single", "collection"]
    manifest_id: str
    output_identity: str

class ExecutionBudget(Protocol):
    max_reduction_depth: int
    def lease(self, kind: Literal["llm", "document", "slice", "reduction"], *, model: str | None = None, endpoint: str | None = None): ...
    def child(self, executable_id: str, depth: int) -> "ExecutionBudget": ...

@dataclass(frozen=True)
class Provenance:
    source_manifest_id: str | None
    source_member_ids: tuple[str, ...]
    parent_aggregate_id: str | None
    pipeline_fingerprint: str
    task_fingerprint: str | None
    prompt_fingerprint: str | None
    reducer_profile: str
    reducer_contract_version: str
    input_contract: ContractRef
    output_contract: ContractRef
    permitted_model_metadata: Mapping[str, object]
```

`TaskExecutable` references an existing named Task/prompt; `PipelineExecutable` references a named, acyclic mini-pipeline. Both use the existing LLM client, audit path, tokenizer and endpoint scheduling. They never accept credentials in persisted config. `PipelineExecutable` validates that its reference is not in `ancestor_executables`; `depth + 1 <= max_reduction_depth` (v1 default 1, hard maximum 2).

## 6. Exact opt-in v1 configuration contract

```yaml
# Absent means untouched legacy behavior.
reduction:
  enabled: true
  profile: concat_text                 # canonical reducer name
  profile_version: "1"
  options: {}
  plugins:                             # optional; same declaration style as Output Profiles
    - module: my_package.reducers
    # or: {name: custom, reducer: my_package.module:factory, aliases: [old_name]}

  controller:
    type: single_pass                  # single_pass | fixed_rounds | adaptive_hierarchical
    max_rounds: 1
    fixed_rounds: null                 # required only for fixed_rounds
    fan_in: 8
    target:
      metric: tokens                   # tokens | characters | records
      max: null
    min_reduction_ratio: 0.05          # (input-output)/input
    stall_rounds: 1
    fail_on_growth: true
    max_growth_ratio: 1.0
    quality_hooks: []                  # named metric hooks only; no universal evaluator

  worker:                              # optional for pure deterministic single-pass reducer
    task: Summary-toTWZH               # exactly one of task / pipeline_ref
    # pipeline_ref: compact_document_v1

  contracts:
    input: {name: text, version: "1"}
    output: {name: text, version: "1"}

  ordering:
    mode: stable                       # stable | irrelevant | reducer_defined
    key: source_ordinal                # required for stable collections

  partial_failure:
    mode: require_all                  # require_all | threshold
    min_success_ratio: 1.0
    min_success_count: 1
    allowed_failure_classes: []
    allow_partial_with_warning: false

  execution_budget:
    max_active_llm_calls: null         # null derives once from model/root n_process
    per_model: {}
    per_endpoint: {}
    document_workers: null
    slice_workers: null
    reduction_workers: 1
    max_reduction_depth: 1             # allowed 0..2
    max_tokens: null                   # optional accounting guard, not billing truth
    max_cost: null

  artifacts:
    retention: keep_failed             # keep_final_only | keep_failed | keep_all_debug
    ttl_days: 7
    pinned_for_resume: true

collection:                            # optional; absence = current one-source-member work item
  mode: explicit                       # explicit | query | grouped
  collection_id: daily-news-2026-09-18
  version: 1
  parent_manifest_id: null
  source_kind: elasticsearch           # sql | elasticsearch | filesystem
  members: []                          # explicit only; logical IDs/versions, no credentials
  query: null                          # source-adapter declaration; snapshot exactly once
  group_by: []                         # grouped only
  ordering:
    key: publish_time
    direction: asc
    tie_breaker: id
  window:
    time_field: published_at
    time_basis: publish
    start: "2026-09-18T00:00:00+08:00"
    end: "2026-09-19T00:00:00+08:00"  # half-open [start,end)
    timezone: Asia/Taipei
    cutoff: "2026-09-19T01:00:00+08:00"
    watermark: "2026-09-19T00:30:00+08:00"
```

Canonical reducer names: `concat_text`, `concat_json_list`, `legacy_json_deep_merge`, `composite`, `semantic_llm`, and `structured_relational`. V1 initial registry ships only the three legacy adapters; later PRs activate the others. Accepted aliases are normalized hyphen/space-to-underscore plus explicit registry aliases. Do not overload `merge_strategy` with new profiles.

Compatibility mapping:

- no `reduction` block: current `merge_slices` and aliases route directly to legacy code;
- `reduction.enabled: false`: same as absent;
- explicit `reduction`: `merge_slices` may coexist only if it agrees with `legacy_json_deep_merge`; otherwise configuration fails before work is claimed;
- explicit `concat_text`/`concat_json_list` ignores no legacy flag silently—conflicting `merge_slices=true` is invalid;
- no `collection` block: one existing source file/row/document is one Logical Work Unit;
- collection requires explicit opt-in and a persisted manifest before worker dispatch.

Invalid combinations rejected at config load:

1. both `worker.task` and `worker.pipeline_ref`, or neither when a controller round needs a worker;
2. adaptive controller without a finite target and finite `max_rounds`;
3. `fixed_rounds` without positive `fixed_rounds` or with a conflicting `max_rounds`;
4. stable ordering without a deterministic key/tie-breaker for collection sources;
5. query/grouped collection for filesystem;
6. time collection without timezone and half-open start/end/cutoff semantics;
7. threshold failure mode without valid count/ratio; partial continuation without explicit warning marking;
8. plugin aliases colliding with built-ins;
9. input/output contract mismatch with reducer declarations;
10. pipeline self-reference, ancestor reference, graph cycle, or depth above 2;
11. child executor declaring its own pool/budget;
12. semantic reducer without Task/PipelineRef, context limit, and observable failure policy;
13. resume artifact whose manifest, worker, reducer, prompt, schema, or contract fingerprint differs;
14. `keep_final_only` while unfinished checkpoints are pinned for resume.

## 7. Legacy compatibility and required golden tests

| Legacy scenario | Future mapping when explicitly adapted | Default behavior | Golden assertion before routing |
|---|---|---|---|
| Text concat | `concat_text` | unchanged direct combine | exact bytes/newlines/order |
| JSON-list concat/flatten | `concat_json_list` | unchanged direct combine | dict/list flatten, non-dict filtering |
| Deep dict merge | `legacy_json_deep_merge` | unchanged flag path | scalar/list/type report and envelope |
| Merge disabled | concat adapter selected internally only after parity | direct legacy | list shape |
| Merge enabled | legacy deep adapter | direct legacy | one vs many slice shape |
| Single slice | legacy one-slice branch | direct legacy | list envelope retained |
| Multi-slice | sorted combine | direct legacy | lexical order |
| Malformed JSON | legacy fallback | direct legacy | pure-text and mixed-valid cases |
| Empty/no-topic | legacy skip | direct legacy | `[]` vs empty text |
| Single-stage | Task filesystem flow | unchanged | retry/non-retry and cleanup |
| Multi-stage | existing stage runtime | unchanged | barriers, snapshots, manifest, final combine |
| TXT/file | file sink | unchanged | combined path and source backup |
| SQL | Row Merger -> SqlSink | unchanged | PK update, retry, flatten |
| ES | Row Merger -> ESSink | unchanged | `_id` resolution, bulk retry |
| Output Profile | final profile bridge | unchanged | alias/plugin/validation failure |
| Row Merger | downstream of reducer | unchanged | source resolution and envelope |
| Stage writeback | stage manifest selector | unchanged | selected stage only, no fallback corruption |

PR A must add golden coverage for every row, including the duplicate orchestrator/Row-Merger combine surfaces. Only after these pass on baseline and adapter code may opt-in routing be introduced.

## 8. Hierarchical reduction state machine

```text
CREATED
  -> PREPARE_ROUND (validate contracts, cancellation, depth, resume fingerprint)
  -> SPLIT         (stable chunk IDs and ordinals; context-aware fan-in)
  -> DISPATCH      (lease shared budget; execute worker per chunk)
  -> COLLECT       (record successes/failures atomically)
  -> POLICY        (retry retryable children; apply explicit partial policy)
  -> REDUCE        (Reducer Profile; never source/sink logic)
  -> MEASURE       (tokens/chars/records + optional quality hook metrics)
  -> CHECKPOINT
  -> DECIDE
       target reached / single pass -> FINISHED
       cancelled                   -> CANCELLED
       retryable round failure     -> PREPARE_ROUND(same round/attempt+1)
       partial policy rejected     -> FAILED
       output grows beyond guard   -> FAILED_GROWING
       stalled N rounds            -> STALLED (fail or explicit partial)
       max rounds reached          -> MAX_ROUNDS (fail or explicit partial)
       continue                    -> PREPARE_ROUND(next round, previous output)
```

A checkpoint includes execution/work-unit/stage/round/attempt IDs, ordered input artifact IDs, output artifact ID, metrics, failure records, controller decision, fingerprints, and lineage. Resume loads only the newest complete atomic checkpoint matching every fingerprint; incomplete temp files are ignored. Cancellation stops new leases, signals existing calls through current cancellation facilities where possible, collects terminal statuses, and writes a cancelled checkpoint. Retries do not change member/chunk identity or manifest membership.

Default adaptive stop logic is deterministic: target metric first; then growth guard; then minimum ratio/stall counter; then max rounds. Optional quality hooks return named metrics and acceptance booleans; they cannot mutate results and an unavailable hook fails or warns only as configured.

## 9. Collection lifecycle and cross-cutting decisions

```text
RESOLVE_SCOPE (source adapter validates query/group/window/order)
 -> SNAPSHOT_MEMBERS (resolve once; canonical deterministic ordering)
 -> PERSIST_MANIFEST (atomic immutable body + manifest_id)
 -> CREATE_WORK_UNIT / stable aggregate_output_id
 -> DISPATCH_MEMBER_EXECUTABLES (shared budget; cache compatibility check)
 -> COLLECT_RESULTS_AND_FAILURES
 -> APPLY_PARTIAL_FAILURE_POLICY
 -> REDUCE (possibly deterministic composite then semantic stage)
 -> FINAL_OUTPUT_PROFILE_VALIDATE
 -> IDEMPOTENT_SINK_UPSERT
 -> PERSIST_WRITE_RECEIPT / COMPLETE
```

### 9.1 Incremental and late arrivals

`collection_id` is the stable business identity; integer `collection_version` plus content-derived `manifest_id` identifies one snapshot. `parent_manifest_id` links successors. A running manifest is immutable. Retry/resume reloads the same manifest; it never reruns the query. Late arrivals create version N+1 with a new cutoff/watermark and parent link. V1 recomputes the full new snapshot, but member and worker fingerprints permit future delta reuse. True incremental reducer state is deferred.

### 9.2 Aggregate idempotency

Compute:

```text
aggregate_output_id = SHA-256(
  canonical(work_unit scope + manifest_id + pipeline/task fingerprint
            + reduction config fingerprint + output contract/profile version)
)
```

The sink performs upsert/compare-and-set by this identity. For existing-row SQL/ES workflows the established PK/`_id` update remains. For aggregate destinations, schema/mapping must provide a unique key/document `_id`; the write receipt records identity, sink target alias (not credentials), payload fingerprint and acknowledgement. Retrying after a lost acknowledgement reads/upserts the same identity and cannot insert a second logical aggregate.

### 9.3 Lineage and aggregate-of-aggregates

Persist secret-free provenance beside artifacts and permitted sink metadata: source manifest/member versions, parent aggregate ID, pipeline/task/prompt fingerprints, reducer profile/contract, schema contracts, and allowlisted model metadata. A prior aggregate becomes `SourceMemberRef.aggregate_identity`; no special workflow type is required. Every higher-level manifest records those identities and contract versions.

### 9.4 Partial failure

Generic policy owns thresholds and allowed failure classes. Task configuration chooses values. `require_all` is default. Threshold mode evaluates after configured retries, never silently. A successful partial `ReducerResult` has `partial=true`, warnings, counts/classes, omitted member IDs/fingerprints, and coverage ratio. Output Profile still validates payload. Sink writeback is blocked unless the threshold passes and `allow_partial_with_warning=true`; metadata/receipt carries partial status.

### 9.5 Ordering

Reducer metadata declares `requires_stable`, `preserves`, `irrelevant`, or `reorders`. Manifest stores ordinal and ordering policy. SQL must use explicit `ORDER BY` with unique tie-breaker; ES uses explicit sort plus tie-breaker/PIT-compatible snapshot mechanism; filesystem snapshot sorts normalized relative path unless explicit order is supplied. Rank/top-k declares `reorders` and records score/tie-break policy.

### 9.6 Time window, timezone, cutoff, watermark

These fields are source/collection semantics only. Windows are half-open `[start,end)` in the declared IANA timezone and record chosen time basis/field. `cutoff` says when membership was resolved; `watermark` records source completeness policy. Reducers receive the immutable member list and never interpret “today.” Late data generates a successor manifest.

### 9.7 Cache/reuse

There is currently restart reuse through Success files and stage snapshots, but no contract-aware global cache. V1 does not add one. Every member artifact nevertheless records `source version/fingerprint + executable fingerprint + input/output contracts + prompt/model-safe fingerprint`; resume/reuse rejects any mismatch. Reducer/schema versions are part of aggregate keys. A future cache can index the same tuple without redesign.

### 9.8 Shared execution budget

The root converts current settings once: `n_process`/`nProcess` informs active LLM capacity; row setting caps document leases; slice setting caps slice leases; endpoint/model limits create keyed semaphores. Every child receives the same coordinator and borrows leases in a documented order to avoid deadlock. A child may schedule tasks but may not construct multiprocessing/thread pools independent of the coordinator. Depth is an additional safety check, not workload control. Token/cost budgets are optional monotonic counters and cancellation guards.

### 9.9 Artifact retention and GC

- Always retain until completion/resume expiry: collection manifest, latest complete checkpoint per active branch, final result, failure summaries, write receipt, lineage, and required LLM audit.
- `keep_final_only`: remove successful chunk/round bodies after receipt; retain fingerprints/metrics/lineage.
- `keep_failed`: above plus failed input/output evidence subject to security policy.
- `keep_all_debug`: retain all round artifacts.
- `ttl_days` never removes `pinned_for_resume`; completion unpins according to policy.
- GC works from manifest/checkpoint reachability, uses atomic rename/delete, and never scans source data as authoritative state.

### 9.10 Reducer/schema contract versioning

Every input, reducer result, checkpoint and aggregate carries `reducer_profile`, `reducer_contract_version`, input/output `ContractRef`, and Output Profile/schema version when applicable. Registry factories declare accepted contracts. A mismatch fails before reducer execution or reuse. V1 provides no migration framework: rerun from compatible source artifacts or explicitly supply a future migration adapter.

## 10. Acceptance designs

### 10.1 Structured relational multidimensional case

1. Treat each slice output as its own namespace using stable slice artifact ID, yielding internal IDs such as `slice-000:S0-E1`; preserve original local ID and evidence provenance.
2. A declarative relational profile identifies entity collections, local ID paths, reference paths, canonical prefix/order, scalar conflict policies, and validation constraints. It is generic mapping—not hard-coded Event classes or a graph database.
3. Rewrite every declared reference to namespaced IDs and fail on missing/ambiguous references before deduplication.
4. Apply deterministic exact duplicate keys first. Optional semantic duplicate consolidation is a separately audited executable; it emits merge decisions/confidence/provenance and never silently falls back.
5. Resolve article-level scalar fields with explicit field policies (`require_equal`, source-priority, longest, semantic worker); unresolved conflicts are warnings or failures, not implicit `prefer_left`.
6. Assign final canonical IDs in stable order (`E1..En`) and remap all references once.
7. Run relational integrity validation: unique IDs, existing targets, allowed cardinality, evidence coverage.
8. Pass the final outer envelope to strict `multidim_event` Output Profile. Profile rejection blocks sink writeback.

This solves local `E1` collisions and linked arrays without making the engine event-specific.

### 10.2 Hierarchical summary

```text
round 1 input artifact A0: 120,000 tokens
  -> stable chunks A0/C000..C031
  -> worker summaries + concat/semantic reducer
  -> checkpoint R1/A1: 18,000 tokens, ratio .85, lineage to C*
  -> decision CONTINUE (target 2,000)
round 2 A1: 18,000
  -> chunks R2/C000..C005
  -> A2: 4,800, ratio .733
  -> decision CONTINUE
round 3 A2: 4,800
  -> chunks R3/C000..C001
  -> A3: 1,850, ratio .615
  -> decision FINISH target reached
  -> Output Profile validation -> next business stage receives A3
```

Each round records estimator/context source, input/output metrics, prompt/reducer fingerprints, member/chunk provenance, failures and decision. Rounds remain internal to one business stage. Resume starts at the last compatible complete checkpoint.

### 10.3 643-document daily news collection

1. ES adapter resolves `[2026-09-18T00:00, 2026-09-19T00:00)` Asia/Taipei by `published_at`, cutoff and watermark, using explicit sort/tie-breaker; stores 643 IDs, versions/fingerprints and ordinals in `daily-news-2026-09-18/v1` manifest.
2. Output identity is derived before calls. Per-document compact analysis runs under shared document/slice/LLM budget; oversized members may use one nested hierarchical ReductionStage within depth limit.
3. Suppose 620 succeed, 18 schema failures and 5 timeouts after retries. Configured threshold decides explicitly. If accepted, result is marked partial with all 23 failures and coverage; otherwise no aggregate write occurs.
4. A composite reducer runs declared steps `dedup -> cluster -> rank -> top_k(10)`. Ordering changes are intentional and score/ties are recorded.
5. A TaskExecutable performs semantic synthesis with existing client/audit/context checks and inherited budget; failure is observable and has no implicit structural fallback.
6. Final briefing passes its Output Profile. Sink upserts `aggregate_output_id`; lost acknowledgement retries same ID. Receipt and lineage include the manifest and contributing member IDs.
7. Late news creates v2 with v1 parent; v1 never mutates. V1 implementation recomputes, while compatible member artifacts may be reused only when future cache support is explicitly enabled.

### 10.4 Aggregate-of-aggregates

- Seven daily aggregate outputs, each with aggregate ID, manifest ID, output contract/schema version, time window and lineage, become members of a weekly manifest.
- Four weekly aggregates become a monthly manifest; three monthly aggregates become quarterly.
- At every level the member fingerprint, parent aggregate identity, ordered window, pipeline/reducer/prompt fingerprints and contracts survive. Incompatible schema versions fail before dispatch.
- The same collection lifecycle and ReductionStage execute each level; no DAG, scheduler type, or special aggregate reducer is introduced.

## 11. Phased PR roadmap

| PR | Objective and likely files | Tests | Config / behavior | Risk, exit, rollback, dependency |
|---|---|---|---|---|
| **A Characterization / Golden Tests** | Add fixtures/tests around `utilities/combine_utils.py`, `slice_merge.py`, prompt multistage, Row Merger, SQL/ES sinks, Output Profiles. No production files unless test seams strictly require no-op injection. | Entire §7 matrix. | None; **production change NO**. | Low. Exit: baseline behavior frozen. Rollback: tests only. Dependency: plan. |
| **B Contracts, registry, legacy adapters** | New `reduction/contracts.py`, `registry.py`, `reducers/legacy.py`, unit tests; adapters call existing helpers. | Registry, aliases, plugins, order, audit/warnings/metrics/contracts plus parity against A. | No accepted runtime routing yet; **NO**. | Medium duplicate-abstraction risk. Exit: exact adapter parity. Rollback: remove package. Depends A. |
| **C Strict config + opt-in single-pass routing** | `reduction/config.py`, `engine.py`, prompt integration; `combine_utils` remains default facade. | absent/disabled/conflict/invalid/plugin config; TXT/SQL/ES opt-in parity. | Adds `reduction`; legacy default unchanged; **YES only when opt-in**. | High. Exit: no-default diff. Rollback: disable block. Depends B. |
| **D Hierarchical controller/artifacts** | `controllers.py`, `chunking.py`, `artifacts.py`, TaskExecutable integration, atomic checkpoints. | all controller state transitions, resume/cancel/stall/growth/empty/context limits; TXT then SQL/ES single-doc integration. | Adds adaptive fields; **opt-in YES**. | High token/retry risk. Rollback to single_pass. Depends C. |
| **E Shared Execution Budget before collections** | `budget.py`, adapters in prompt dispatch/producer; translate current parallel controls once. | lease limits, nested contention, cancellation, endpoint/model caps, no child pools. | Optional budget settings; defaults derived compatibly; **new reduction only**. | Highest oversubscription risk. Exit: stress test bounded calls. Rollback reduction to serial. Depends D. |
| **F Logical Work Unit + immutable manifests** | `collections/contracts.py`, `identity.py`, `lifecycle.py`, atomic artifact store; no source query execution initially. | explicit manifests, canonical hash, lineage, version parent, ordering/window validation, stale resume rejection. | Adds `collection.mode=explicit`; **opt-in YES**. | Medium identity risk. Depends E. |
| **G SQL/ES collection adapters + idempotent sink upsert** | collection adapters, SQL/ES source resolution, integration/writeback and destination schema docs. Filesystem explicit snapshot only. | query/group snapshot, timezone/watermark, retry same manifest, aggregate ID/upsert, partial policies, source ordering. | Query/group collection; **opt-in YES**. | Highest writeback risk. Rollback disable collection route; manifests remain audit. Depends F. |
| **H Deterministic composite reducers** | `reducers/deterministic.py` for dedup/cluster/rank/top-k where deterministic/configured. | stable ties, provenance, partial data, contract mismatch. | New profiles/options; **opt-in YES**. | Medium. Depends B/F. |
| **I Semantic reducer** | `reducers/semantic.py`, Task/Pipeline executable adapters, audit/context enforcement. | Task and PipelineRef, timeout/schema failure, budget, no silent fallback, lineage. | `semantic_llm`; **opt-in YES**. | High hallucination/loss. Depends D/E/H. |
| **J Structured relational reducer** | `reducers/relational.py`, declarative relationship schemas and multidim acceptance config/docs. | namespace/remap/dedup/canonical IDs/scalar conflicts/integrity/final profile. | `structured_relational`; **opt-in YES**. | High schema risk. Depends H; semantic dedup optionally I. |
| **K ReductionStage + bounded PipelineRef nesting** | multistage integration, `execution.py`, cycle/depth validators; do not modify round-as-stage identity. | self/cycle/depth, shared budget, nested oversized collection member, progress/cancel/resume. | Allows worker PipelineRef; **opt-in YES**. | Highest orchestration risk. Depends E-G/I. |
| **L Production hardening and retention/GC** | policies, artifact GC, operational docs/metrics, fault injection. | crash points, atomicity, GC reachability, scale/load, security redaction, all integrations. | Retention operational settings; **YES for opted-in workloads**. | Medium. Depends all prior. |

The original suggested sequence is corrected in two ways: shared Execution Budget moves before collection fan-out and semantic work, and immutable manifests precede deterministic collection composites. Otherwise collection nesting could ship with uncontrolled pools and unstable identity.

## 12. Risk register

| Risk | Mitigation / acceptance gate |
|---|---|
| Backward incompatibility | Absence/disabled block bypasses new code; PR A goldens; facade retained. |
| Duplicate merge abstractions | Explicitly quarantine skeleton `pipeline/merge`; one small Reducer protocol only. |
| Nested parallelism / GPU oversubscription | Inherited leases; budget PR before collections; endpoint/model stress tests. |
| Token explosion | tokenizer/context estimator, fan-in planning, max rounds/tokens, growth guard. |
| Non-converging reduction | deterministic ratio/stall/max-round states; no LLM stop judge by default. |
| Retry amplification | stable round/member IDs, bounded attempts, checkpointed terminal failure classes. |
| Duplicate aggregate writeback | precomputed aggregate ID, sink upsert/unique key, write receipt. |
| Partial member failures | default require-all; explicit thresholds and partial marker/provenance. |
| Stale manifest / late arrivals | immutable manifest; resume same ID; successor version and parent. |
| Ambiguous time windows | time basis, IANA timezone, half-open bounds, cutoff/watermark required. |
| Source ordering drift | explicit key + unique tie-breaker stored in manifest; reducer declaration. |
| Artifact growth | retention modes, reachability GC, TTL and resume pin. |
| Cancellation complexity | shared token, stop new leases, checkpoint terminal child states. |
| Stage/round identity confusion | separate IDs/artifact namespaces; rounds never enter StageDefinition list. |
| Work-unit identity ambiguity | canonical manifest/scope and output identity contracts. |
| Sink/writeback-source ambiguity | core returns artifact; source selection/Row Merger/sink stay downstream. |
| Semantic hallucination/data loss | explicit semantic profile, audit/quality hooks, no silent fallback, strict final profile. |
| Schema contract incompatibility | versioned ContractRef and hard mismatch rejection. |
| Stale cache reuse | all relevant fingerprints in artifact key; no cache in initial v1. |
| Cycle/nesting errors | ancestor executable chain, preflight graph validation, hard depth <=2. |
| Credentials in lineage | allowlisted model metadata and logical locators only; sink redaction defense. |
| Existing combine invoked twice | characterization of orchestrator and Row Merger ownership before routing. |
| Stage manifest races | new artifacts atomic/content-addressed; do not reuse mtime heuristic for collections. |

## 13. Explicit non-goals

V1 is not a generic DAG engine, arbitrary recursive Stage/Reducer runtime, graph database, filesystem database scheduler, mandatory semantic reducer, rewrite of legacy combine, general AI evaluation platform, distributed global cache, automatic semantic repair, or schema migration framework. It does not provide true delta/incremental aggregation; it preserves contracts that permit it later.

## 14. Open questions requiring implementation-time evidence

1. Which SQL aggregate destination schema/index is the first supported target, and can it enforce `aggregate_output_id` uniqueness without a migration affecting existing tables?
2. Which ES snapshot mechanism/version fields are guaranteed by supported deployments (PIT + sort, `_seq_no`/`_primary_term`, application version, or content hash)? The adapter must declare what it actually captured.
3. Should Output Profile validation be extracted to a sink-neutral service before SQL aggregate production, or is ES the first strict-profile collection sink? Do not claim uniformity until tested.
4. Which tokenizer is authoritative when a mini-pipeline changes model between stages? Proposed answer: estimator belongs to each executable/model, while controller stores metric source per round.
5. How should current synchronous APIs surface cancellation into in-flight HTTP calls? Until supported, cancellation is cooperative between calls and records the limitation.
6. What retention period is legally/operationally permitted for failed prompts and source-derived evidence? Defaults must be deployment policy, not guessed.
7. The intended predecessor plan commit was unavailable in the supplied clone; reviewers should compare this reconstructed v2 against PR #177 before merge to ensure no still-valid draft decision was omitted.

## 15. Completion criteria for Phase 0

- This plan and project memory are the only changed content.
- No new runtime package or configuration parser is implemented.
- All proposed integration names above refer to real current seams or are explicitly listed as new files.
- Compatibility claims are tied to inspected source behavior; unknown deployment guarantees are open questions.
- No credential, private endpoint, or connection string is present.
- `git diff --check` passes and a static changed-file allowlist confirms documentation-only changes.

**Recommendation:** merge this plan, then start with **PR A — Characterization / Golden Tests**. No prerequisite production refactor should come first; the current duplicated combine/writeback surfaces make behavior capture the safest prerequisite for every later seam.
