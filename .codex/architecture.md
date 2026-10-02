# Project Architecture

## Current Summary

- Input modes (TXT, Excel/CSV/tabular, SQL/SQLite/SQL Server, Elasticsearch) feed shared prompt/task and reduction infrastructure; source-specific adapters and sinks remain separated from source-independent reduction contracts.
- Reduction layers: strict `ReductionConfig` -> configured reducer registry/factory -> single-pass or D1/D2 hierarchical controller/checkpoints. Collection manifests and aggregate sinks are distinct from business stage manifests and row writeback.
- Production LLM calls flow through prompt rendering, `TokenizerWrapper`, `PromptAPIPipeline`, and leaf-only `ExecutionBudget` leases. Orchestrators may create nested thread pools but never retain permits while waiting.
- `Executable` workers include `TaskExecutable`, `StagePipelineExecutable`, bounded `PipelineRefExecutable`, and K2 `ReductionStageExecutable`; no general graph/workflow abstraction exists.

## Module Boundaries

- `reduction/execution.py`: immutable executable results/context, local registry, task executable, and K2 nesting state.
- `reduction/executable_pipeline.py`: ordinary in-memory stage pipeline and bounded named references.
- `reduction/stage.py`: source-independent ReductionStage, shared tokenizer-boundary resolution, round preparation, canonical stage semantic fingerprint.
- `reduction/nested_execution.py`: input-preparer contracts and bounded nested ReductionStage adapter.
- `reduction/stage_config.py`: separate strict parsers for stages and nested stage executables; registry population remains caller-owned.
- `reduction/hierarchical.py` and `artifacts.py`: D1 controllers/checkpoints; unchanged by K2.
- `reduction/runtime_text.py`: legacy D2 text adapter identity; unchanged by K2.

## Current Data Flow

1. Caller creates one root runtime context and shared process-local `ExecutionBudget`.
2. Outer `ReductionStage` maps ordered prepared members without leasing permits.
3. A PipelineRef derives an immutable ref-stack context, resolves only ordinary pipeline/ref/nested-stage targets, and rejects cycles or a fifth active name.
4. `ReductionStageExecutable` derives nested depth 1, prepares one raw member into ordered child inputs, and invokes its child stage. A second nested boundary fails.
5. Child stage workers are direct tasks or bounded refs to ordinary pipelines. Only their task leaves lease budget capacity.
6. Child reduction uses existing reducers/controllers/checkpoints and returns one compact output. Wrapper metadata preserves child audit/provenance/metrics in bounded namespaces; outer stages currently consume worker outputs rather than aggregate every member lineage.
7. Outer reducer preserves original member order and produces the collection output.

## K2 Safety and Identity

- Hard v1 bounds: nested reduction maximum 0 or 1 (default 1); PipelineRef maximum 1..4 active names (default 4). State is frozen and every transition returns a new context.
- Execution and fingerprint traversal use the same transitions. Self, indirect, and longer cycles fail deterministically without `RecursionError`.
- PipelineRef targets are exactly `StagePipelineExecutable`, `PipelineRefExecutable`, and `ReductionStageExecutable`; nested stage workers are exactly `TaskExecutable` or `PipelineRefExecutable`.
- ReductionStage v2 identity includes actual reducer profile/contract/options, controller/options, worker semantics, and round-preparer semantics. It excludes concurrency, budget capacity, checkpoint paths, endpoint/credential data, and runtime identity.
- Nested semantic or composite-semantic reducers fail at construction/config parsing. Ordinary top-level semantic reduction remains available.
- Identity and tokenizer input preparers make initial child inputs explicit. Both initial and round tokenizer paths share production effective-task/InputCutLen resolution and acquire no budget lease.

## Out of Scope / PR L

- Initial/member result cache, reusable member store, retention, TTL, cleanup/GC, cancellation, full member-lineage aggregation, partial-success thresholds, and skipped-member policies.

## Recent Changes

- 2026-10-02: K2 bounded nesting, ref cycles/depth, semantic stage identity, input preparation, strict config, and one production E2E were added locally; hosted acceptance is pending.
- 2026-10-01: K1 executable and non-nested stage contracts merged in PR #191 after hosted 19/19 acceptance.
- 2026-09-30 to 2026-10-01: semantic and structured-relational reducers merged.
- 2026-09-19 to 2026-09-30: Reduction Engine A-H established compatibility, reducers, hierarchical execution, budgets, collection identity/adapters/sinks, and deterministic composites.

## Archived History

- `architecture.md-20261002-000000.md` — full architecture history through pre-hosted K2 implementation.
