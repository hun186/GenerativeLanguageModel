# Architecture and Design Decisions

## Current Summary

- Prefer strict explicit configuration, fail-closed validation, stable normalized semantic fingerprints, instance-local registries, immutable identity/traversal data, ordered results, and atomic checkpoint/output boundaries.
- Operational scheduling and filesystem placement do not define successful output semantics. Credentials, endpoints, timestamps, PID/thread identity, runtime reprs, and budget capacity never enter semantic fingerprints.
- Parent orchestration does not lease leaf capacity; only production LLM leaves do.
- Keep D1/D2 historical checkpoint and runtime contracts stable unless a scoped corrective explicitly versions the affected identity.

## Active Decisions

### K2 bounded execution tree

- Permit one nested `ReductionStageExecutable` below a root stage and at most four active PipelineRef names. Configuration cannot raise these hard v1 ceilings; zero explicitly disables nested reduction.
- Carry traversal state through frozen derived `ExecutionContext` objects only. Do not use global, registry-owned, thread-local, or in-place traversal state.
- Execute and fingerprint through identical guard transitions so illegal graphs never receive valid-looking identities and cycle detection never relies on recursion failure.
- PipelineRef resolves exactly ordinary stage pipelines, other bounded refs, or bounded nested stages. Nested stage workers resolve exactly direct tasks or PipelineRefs. Do not introduce Sequence/DAG/workflow execution.
- Nested semantic/composite-semantic reducers fail closed because the PR I generic semantic runtime lacks a complete nested fingerprint contract. Top-level semantic reduction stays supported.
- Preserve child metadata under namespaces, but defer outer member-lineage aggregation and partial success to PR L.

### Semantic identity and compatibility

- `ReductionStage` v2 canonical metadata includes the actual configured reducer profile/contract/options, controller/options, worker metadata, and optional round-preparer metadata.
- `TokenizerRoundPreparer` v2 and `TokenizerInputPreparer` share authoritative production `effective_input_cut_len(task)` resolution, with deterministic K1-compatible fallback.
- K1-native checkpoints may miss/recompute because stage identity is stronger. D1 checkpoint schema/version, D2 `TextRoundRuntimeAdapter`, legacy combine checkpoints, and historical execution fingerprints are unchanged and require no migration.
- Input-preparer semantics belong in the parent worker identity; actual prepared data belongs naturally in the child input/run fingerprint rather than executable metadata.

### Existing Reduction Engine invariants

- Explicit reduction is opt-in and separate from legacy `merge_slices`; reducers are fresh configured instances from one registry/factory.
- Hierarchical text uses concat reduction, deterministic controllers, completed-round atomic checkpoints, and stable execution fingerprints.
- Collection membership is snapshotted once into immutable ordered manifests; SQL/ES aggregate writes use deterministic identities and lineage-safe idempotent upsert.
- Semantic reduction is one production call per invocation; structured relational reduction is deterministic two-pass rewriting with complete provenance.
- Shared execution budgets are process-local hard ceilings, not distributed schedulers.

### Scope deferred to PR L

- No member cache, reusable result store, retention/TTL/GC, cleanup scheduler, cancellation framework, member-lineage aggregation, partial collection result, minimum-success threshold, or skip-failed-member behavior.

## Recent Changes

- 2026-10-02: adopted K2 bounded tree, immutable guard, nested semantic restriction, and strengthened native stage identity decisions.
- 2026-10-01: K1 effective-task, InputCutLen, callable-source, model/tokenizer, and metadata namespace correctives accepted in PR #191.
- 2026-09-30 to 2026-10-01: PR I semantic and PR J relational constraints accepted.
- 2026-09-19 to 2026-09-30: PR A-H compatibility, reducer, hierarchical, budget, collection, adapter/sink, and composite decisions accepted.

## Archived History

- `decisions.md-20261002-000000.md` — full decision history through pre-hosted K2 implementation.
- `decisions.md-20260920-013654.md` — earlier history through D2.
