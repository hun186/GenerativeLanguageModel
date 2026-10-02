# Project Memory

## Current Summary

- Python multi-source document/tabular processing and LLM multi-stage analysis framework. Reduction Engine A-J and K1 are merged; K2 is implemented on its feature branch but remains pending fresh hosted 20/20 acceptance. PR L is not implemented.
- Production reduction uses strict explicit configuration, source-independent reducer contracts, immutable collection manifests, aggregate sinks, shared process-local execution budgets, deterministic/semantic/relational reducers, executable task/stage workers, and checkpoint-backed hierarchical text reduction.
- Parent orchestration never leases leaf permits. Task/semantic-runtime calls alone lease from the root `_execution_budget`.
- D1 checkpoint contract/version and D2 `TextRoundRuntimeAdapter` historical identity are compatibility boundaries. K2 strengthens only K1/K2-native stage identities.
- Full requirements installation in this environment is blocked by the pinned GitHub `peft` dependency through a CONNECT proxy 403. Dependency-light verification works; production E2E requires hosted CI when missing packages prevent local collection.

## Recent Changes

### 2026-10-02 Reduction Engine PR K2 implementation

- Verified baseline ancestry from K1 merge `b74907c2b235bbace9afad4a5b9f676cb85e1748`. K1: PR #191, hosted feature head `5632d16b4eb18eaad830f0b81c1a8356bbb8cbe2`, CI #436 / `36895400626`, offline E2E 19/19 PASS.
- Added frozen `ExecutionNestingState`, one-boundary nested reduction limit, four-name PipelineRef limit, immutable transitions, cycle guards, and identical execution/fingerprint traversal guards.
- Added canonical ReductionStage v2 semantic metadata, shared effective `InputCutLen` resolution, input preparers, bounded `ReductionStageExecutable`, strict nested parser, metadata namespaces, and semantic-child fail-closed validation.
- No workflow/DAG, partial success, cache, retention, cancellation, TTL, or GC was introduced. Canonical roadmap remains `[x] K1`, `[ ] K2`, `[ ] K overall`, `[ ] L` until hosted acceptance.
- Verification: focused K2 tests 19 passed; full reduction suite 355 passed; prompt-pipeline regression selection 16 passed; compileall and diff check passed. Focused local production E2E is blocked on missing `psutil` after requirements install failed at pinned GitHub `peft`; hosted 20-case gate is pending.
- Delivery limitation: the checkout has no `origin`, so the committed branch cannot be pushed and a hosted PR/CI identifier cannot be collected here. `make_pr` metadata was prepared; K2 and PR K remain explicitly unchecked/unmerged.

### 2026-10-01 PR K1 and review correctives

- Introduced executable/task/runtime contracts, ordinary stage-pipeline execution, non-nested PipelineRef, source-independent ReductionStage, strict stage config, tokenizer round preparation, and production task-runtime leaf leasing.
- Correctives fingerprint effective task pools, callable source, model/tokenizer/InputCutLen semantics; generic mappings and nested task mappings resolve consistently. PipelineRef and reducer metadata remain namespaced.
- K1 accepted as PR #191 with hosted 19/19 E2E and merged at the baseline above.

### 2026-09-30 to 2026-10-01 PR I/J

- PR I added single-call semantic reduction through production prompt/tokenizer/HTTP/runtime/budget boundaries, including composite-final support and output cleanup.
- PR J added deterministic structured relational two-pass entity/reference rewriting, strict namespace/config validation, bounded audit, and complete provenance.

### 2026-09-19 to 2026-09-29 Reduction Engine A-H

- A-C froze legacy behavior, created reducer contracts/registry, and routed explicit strict single-pass reduction.
- D1/D2 added controller/checkpoint core and production tokenizer/prompt/LLM hierarchical routing with retry/context-isolation correctness.
- E added one shared process-local leaf budget. F/G added immutable collection identity, SQL/ES collection adapters, and idempotent aggregate upsert. H added deterministic composite reducers.

### 2026-10-02 Memory Compaction

- `.codex/memory.md`, `.codex/architecture.md`, and `.codex/decisions.md` exceeded 20 dated/work blocks and were compacted after full snapshots were saved.
- Archives: `memory.md-20261002-000000.md`, `architecture.md-20261002-000000.md`, and `decisions.md-20261002-000000.md`. Validation uses archive existence, active-file line counts, compileall, and `git diff --check`.

## Archived History

- `memory.md-20261002-000000.md` — complete memory through the K2 local implementation and pre-hosted verification.
- `architecture.md-20261002-000000.md` — complete architecture history through K2.
- `decisions.md-20261002-000000.md` — complete decision history through K2.
- `memory.md-20260920-013654.md` and `memory.md-20260826-041906.md` — earlier snapshots.
- `decisions.md-20260920-013654.md` — earlier decision snapshot.
