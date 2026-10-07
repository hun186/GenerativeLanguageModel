# Reduction Engine v1 operator and developer guide

## Overview

Reduction Engine v1 is the opt-in boundary that turns ordered map/member
results into a final result:

```text
map / member work
-> Reduction
-> optional hierarchical rounds
-> final reduced result
-> optional persisted aggregate/writeback
```

Use it when slice outputs need deterministic combination, semantic synthesis,
relational identifier repair, repeated text compaction, or when an immutable
SQL/Elasticsearch collection snapshot must produce one aggregate. If no
`reduction` mapping is present (or `enabled` is false), legacy behavior is
unchanged. Reduction is never inferred from the input shape.

## Choosing a reducer

The registry normalizes case, whitespace and `-` to `_`. These are the
implemented profiles and aliases:

| Kind | Profile | Accepted aliases | Purpose |
| --- | --- | --- | --- |
| deterministic | `concat_text` | `text_concat` | concatenate text in stable order |
| deterministic | `concat_json_list` | `json_list_concat` | concatenate JSON members, flattening one list level |
| deterministic | `legacy_json_deep_merge` | `legacy_deep_merge` | legacy-compatible recursive object merge |
| deterministic | `dedup` | `deduplicate`, `exact_dedup` | exact first-wins deduplication |
| deterministic | `group` | `group_by` | group by required dotted paths |
| deterministic | `entity_union` | `union`, `exact_union` | one-level entity union |
| deterministic | `rank` | none | stable numeric ranking |
| deterministic | `top_k` | `topk`, `top-k` | retain the first *k* members |
| deterministic | `composite` | none | ordered reducer chain |
| semantic | `semantic_llm` | `semantic` | one LLM task over reducer inputs |
| structured relational | `structured_relational` | `relational` | canonicalize configured IDs and references |

`structured_relational` cannot be a composite step. `semantic_llm` may occur
at most once in a composite and must be its last step. Hierarchical controllers
support only `concat_text`; all other profiles are single-pass.

## Single-pass examples

All examples below are accepted by `parse_reduction_config`.

```yaml
# Text (change profile to concat_json_list for JSON-list concatenation)
reduction:
  enabled: true
  controller: single_pass
  profile: concat_text
```

```yaml
reduction:
  enabled: true
  profile: legacy_json_deep_merge
  options:
    conflict_policy: non_empty # prefer_left, prefer_right, longer_str, non_empty
    dedup_lists: true
    audit_enabled: true
    max_audit_samples: 20
```

Representative deterministic configurations:

```yaml
# Exact first-wins deduplication by a composite key
reduction:
  enabled: true
  profile: dedup
  options: {key_paths: [id, source.name]}
---
# Stable grouping
reduction:
  enabled: true
  profile: group
  options: {by: [day, category]}
---
# One-level entity union
reduction:
  enabled: true
  profile: entity_union
  options: {key_paths: [id]}
---
# Stable ascending rank (descending defaults to true)
reduction:
  enabled: true
  profile: rank
  options: {score_path: metrics.score, descending: false}
---
reduction:
  enabled: true
  profile: top_k
  options: {k: 10}
```

A composite passes each step's payload to the next step. Nested composites are
invalid:

```yaml
reduction:
  enabled: true
  profile: composite
  options:
    steps:
      - profile: dedup
        options: {key_paths: [id]}
      - profile: rank
        options: {score_path: score, descending: true}
      - profile: top_k
        options: {k: 10}
```

Semantic reduction requires the production semantic runtime and a nonblank
task name/instruction:

```yaml
reduction:
  enabled: true
  profile: semantic_llm
  options:
    task: SUMMARY
```

Structured relational reduction is deterministic: it allocates canonical IDs
for each configured entity collection and rewrites only declared reference
fields. Prefix namespaces and entity/reference endpoints must not conflict.

```yaml
reduction:
  enabled: true
  profile: structured_relational
  options:
    entity_sets:
      - name: events
        collection_path: Event
        id_field: event_id
        canonical_prefix: E
    references:
      - collection_path: Person
        field: event_ids
        target: events
```

## Hierarchical reduction

Round 1 reduces the original mapped slices. Each later round uses
`runtime.round_task` to map the preceding aggregate into smaller text chunks,
then reduces those chunks with `concat_text`. A completed round is committed
atomically; resume loads only a validated committed checkpoint chain, never an
in-progress runtime directory.

```yaml
reduction:
  enabled: true
  profile: concat_text
  controller: fixed_rounds
  controller_options:
    rounds: 2
  runtime:
    round_task: SUMMARY
```

```yaml
reduction:
  enabled: true
  profile: concat_text
  controller: adaptive_hierarchical
  controller_options:
    target_max_chars: 12000
    max_rounds: 4
    min_reduction_ratio: 0.1
  runtime:
    round_task: SUMMARY
```

`fixed_rounds` requires a positive integer. Adaptive reduction stops at its
target, maximum rounds, or the controller's progress/convergence boundary.

## ReductionStage and PipelineRef

The developer-facing executable model has four roles:

* `TaskExecutable` invokes one task through `TaskRuntime`.
* `StagePipelineExecutable` runs the existing ordered stage-pipeline state
  machine in memory.
* `PipelineRefExecutable` resolves a named stage pipeline, another reference,
  or a nested reduction through an instance-local `ExecutableRegistry`.
* `ReductionStageExecutable` prepares one input and runs a `ReductionStage`.

This is bounded composition, not a generic DAG. The v1 defaults and hard
limits allow one nested ReductionStage level and at most four PipelineRef
entries. Repeated reference names fail as a cycle; missing/invalid targets and
depth overflow fail closed. Nested ReductionStage executables prohibit direct
or composite semantic reducers; top-level semantic reduction remains valid.

`IdentityInputPreparer` produces one unchanged member. `TokenizerInputPreparer`
uses the production prompt-aware content-preparation boundary (or the existing
TokenizerWrapper path) and fails if prompt overhead or the smallest useful
fragment cannot fit. Hierarchical nested stages similarly require a tokenizer
`round_preparer`. These executable/stage schemas are strict Python parser APIs;
they are not a promise that every root YAML entry point exposes an executable
registry.

## Collection reduction

`LogicalWorkUnit` freezes a stable logical ID, JSON-compatible payload, and
bounded non-secret provenance. `CollectionManifest` freezes the ordered member
snapshot and verifies a fingerprint over membership, order, payload,
provenance, collection ID, and contract version. A later source change creates
a new manifest; it never mutates a running snapshot.

`SQLCollectionAdapter` and `ElasticsearchCollectionAdapter` build manifests
from explicitly ordered/grouped source snapshots. `AggregateOutput` binds a
validated payload to the manifest fingerprint and output key. Its deterministic
`aggregate_output_id` gives SQLite/Elasticsearch aggregate sinks an idempotent
upsert key and rejects conflicting lineage. `AggregateOutput.to_mapping()` (or
`as_logical_work_unit_payload()`) preserves complete lineage when an aggregate
becomes a member of a later aggregate-of-aggregates.

These collection adapters, query specifications, manifest stores, and sinks
are Python APIs. There is no equivalent general-purpose collection YAML schema
in v1; applications must explicitly construct and persist the snapshot.

## Persisted reuse and freshness

SQL/ES destination output is authoritative cross-run reuse state. Reduction
does **not** use transient `.reduction/runtime` directories as a reusable result
cache. A post-v1 evaluation also deferred any second semantic/member result
cache until measured production duplication justifies its operational and
privacy cost; see [the v1.1 cache evaluation](../architecture/reduction_engine_v1_1_cache_evaluation.md).

Persisted semantic processing identity is **opt-in**. If SQL
`semantic_freshness.execution_fingerprint` or Elasticsearch
`rerun.execution_fingerprint` is omitted, no expected processing identity is
bound and legacy output-completeness rules can reuse a nonempty persisted result
even after task/prompt semantics change. Use `auto` to derive the identity from
the effective Executable semantics; SQL also requires a nonconflicting
`processing_identity_column`:

```yaml
# SQL
semantic_freshness:
  execution_fingerprint: auto
  processing_identity_column: processing_fp

# Elasticsearch
rerun:
  execution_fingerprint: auto
```

When enabled, writeback stores the processing identity beside the result and
discovery plus the pre-dispatch recheck compare the expected identity while
validating required outputs. An explicit literal fingerprint remains supported
as an operator-supplied override.

Elasticsearch additionally honors its existing rerun policy: missing output or
required fields, missing/mismatched processing identity, `force_if_missing_meta`,
`force_since`, and `stale_after_days` can make a persisted document pending.
Fresh, valid persisted output is skipped. Operational cancellation,
observability, and retention settings do not enter semantic fingerprints.

## Partial success

`ReductionStage` defaults to strict `require_all`. Partial results require the
explicit stage-level policy below (this belongs to the ReductionStage parser,
not the root single-pass `ReductionConfig` parser):

```yaml
reduction:
  enabled: true
  profile: concat_text
  failure_policy:
    mode: allow_partial
    min_success_count: 2
    min_success_ratio: 0.75
```

Only `ExecutionError` is a recoverable member failure. Cancellation and
unexpected programmer/system faults propagate. Thresholds apply independently
to each batch/round; successful results retain input order, and failed
placeholders are never passed to a reducer. Accepted partial output records
counts plus bounded, payload-free failure provenance (at most 100 details) and
an audit warning without changing the original manifest or aggregate identity.

## Cancellation

Cancellation is cooperative safe-drain behavior:

* stop scheduling new producer/member work;
* do not hard-kill an already-running HTTP request;
* allow in-flight deterministic consumer/merger/writeback work to reach a safe
  state;
* do not start a new semantic continuation after cancellation is observed.

Producer cancellation is therefore not worker teardown. The terminal result is
`cancelled` when the request is observed before the authoritative completed
transition. `ExecutionCancelled` is never treated as partial member failure.

## Observability

Production exposes separate **Recheck Status** and **Reduction Status** views,
allowlisted bounded JSONL events, and lock-protected safe counters. Both Windows
GUI sections are collapsible by default and retain a compact header summary when
collapsed. The Cancel control remains visible in the Reduction header.

Reduction status is mode-aware. A real `ReductionStage` reports stage/member
counters; an explicit legacy `merge_slices` run reports separate legacy merge
attempt/completion/failure counters instead of misleading `Stages: 0 / 0`.
When neither path is active, the panel says that Reduction Engine is inactive.
Events and counters contain identities, state and counts—not source/reducer
payloads. The GUI **Cancel** control uses process-safe IPC to request root
cooperative cancellation. That GUI surface is Windows-only; headless/non-Windows
operation uses the execution cancellation contract and logs rather than
promising the Windows panel.

## Retention and GC

Retention is disabled by default:

```yaml
reduction_retention:
  enabled: true
```

When enabled, separate terminal-checkpoint, incomplete-checkpoint and transient
runtime TTLs govern only L3-owned artifacts during normal sweeps. However,
`cleanup_transient_on_success` defaults to `true`: after a successful
hierarchical final write, eligible transient runtime directories are cleaned
immediately by using an effective transient TTL of zero. Therefore
`transient_runtime_ttl_hours` governs successful runtime artifacts only when
`cleanup_transient_on_success: false`; otherwise it governs leftover runtime
artifacts that reach normal retention sweeps. Bounded scanning/deletion,
ownership markers, expiring execution leases, claim-and-tombstone deletion,
containment checks, and symlink rejection make GC conservative. Incomplete
checkpoint TTL cannot be shorter than terminal TTL. Legacy unmarked artifacts
are never adopted or deleted. See the detailed
[L3 retention contract](reduction_retention_l3.md).

## Failure, retry, and resume

| Artifact | Authority and retry meaning |
| --- | --- |
| committed checkpoint | authoritative hierarchical resume state after full chain validation |
| runtime round workspace | disposable/reconstructable; never cross-run result cache |
| persisted SQL/ES result + processing identity | authoritative cross-run reuse/freshness state |
| persisted Collection Manifest/AggregateOutput | immutable collection membership and aggregate lineage |
| legacy stage artifacts | legacy execution state; deliberately outside L3 ownership/GC |

Malformed or partial checkpoint chains fail closed. Retrying may reconstruct a
runtime round, resume the last committed round, or reuse a fresh persisted
destination result according to the applicable boundary.

## Compatibility

* No reduction configuration means unchanged legacy behavior.
* `reduction.enabled: true` and `merge_slices: true` are mutually exclusive.
* Root configuration rejects unknown keys; single-pass rejects hierarchical
  `controller_options` and `runtime`, while hierarchical mode requires both its
  exact controller options and nonblank `runtime.round_task`.
* Hierarchical mode supports only `concat_text`.
* Structured relational reduction is neither hierarchical nor composable.
* Nested semantic reduction is prohibited; a top-level semantic reducer (or a
  single final semantic composite step) is supported.

## Security and privacy

Execution fingerprints are hashes of normalized semantic configuration.
Effective task and prompt semantics intentionally participate in that hash, so
meaningful prompt changes invalidate persisted reuse. Fingerprint metadata does
not persist plaintext prompts, credentials, raw endpoint URLs,
cancellation/observer objects, operational retention settings, or source
payloads. Retention markers and leases contain bounded operational
ownership/identity/timestamps, not content.
Observability events are allowlisted and payload-free. Collection manifests do
contain the explicitly supplied member payload and provenance, so callers must
not place credentials, private endpoints, prompts, or unrelated secrets in
either field and must protect manifest storage as source-derived data.

## Release audit: Definition of Success

The source/test audit against the architecture plan classifies the v1 contract
as follows:

| Area | Classification | Evidence in the implementation |
| --- | --- | --- |
| opt-in compatibility and strict config | implemented | legacy default, mutual exclusion, strict profiles/controllers |
| single-pass and hierarchical reduction | implemented | deterministic/semantic/relational reducers; fixed/adaptive controllers and atomic checkpoints |
| shared bounded execution | implemented | root `ExecutionBudget` and leaf-only leases |
| collection identity and SQL/ES aggregation | implemented | immutable manifests, adapters, deterministic aggregate ID and idempotent sinks |
| composable stage execution | implemented with explicit limitation | one nested reduction level, four-reference maximum, cycles guarded, nested semantic prohibited |
| reuse/freshness | implemented with explicit limitation | authoritative persisted SQL/ES result reuse; no transient/global member cache |
| failure/cancellation/observability | implemented | explicit partial policy, cooperative safe drain, bounded payload-free production events/counters |
| lifecycle | implemented with explicit limitation | disabled-by-default ownership-based bounded GC; legacy unmarked/stage artifacts excluded |
| universal quality/coverage scoring | future/v1.1 candidate | extension point only; task-specific scoring remains deliberately deferred |
| generic maintenance/migration tools | future/v1.1 candidate | no legacy artifact adoption or general recursive cleanup |
| finer shared-checkpoint coordination | future/v1.1 candidate | one nested checkpointed executable is conservatively serialized |

Reduction Engine v1 A–L implementation is present on `main`, and the
bounded-retention reporting issue found by this closure audit was corrected by
PR #201. The corrective uses a run-local `deletion_budget_exhausted` latch:
after the deletion entry/byte budget is first exhausted, later candidates still
run through validation/classification/counters, while no later deletion is
allowed. Deterministic regressions cover both a malformed tombstone encountered
after budget exhaustion and a smaller artifact encountered after a larger one
exhausts the byte budget.

PR #201 accepted head `62deba6a35d5d5f1d5c82f586d65bc8827e212ef`
passed CI #459 / `37399753801`, offline job `112064086574`, collect 24 and
full gate PASS / 100%, then merged as verified/valid
`91e39503c8e84d17752f9d26a23ff6b34db75b9e`. The runtime release blocker was
therefore resolved. PR #200 final accepted head
`36a40eb37827e33545865203b079aefaab1ba1f4` then passed CI #467 /
`37420475520`, offline job `112128483703`, collect 24 and full gate PASS /
100%, with zero unresolved review threads and a fresh Codex review reporting no
major issues. PR #200 merged as verified/valid
`99d79676b16b7fed54f9cf6e701441db79846cea`. Reduction Engine v1 is therefore
**COMPLETE / RELEASE-READY** on the authoritative `main` baseline; the explicit
limitations above remain deliberate bounded contracts rather than release
blockers.
