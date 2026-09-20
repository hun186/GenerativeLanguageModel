# Architecture Decisions

## Current Summary

- `combine_utils.py` remains the compatibility facade and owns Success discovery, output placement, final writes, and cleanup; focused JSON/slice/reduction modules provide implementation seams.
- Row Merger remains downstream SQL/Table/ES writeback coordination, while Output Profile remains the final strict validation boundary. Reduction Core does not own either boundary.
- Model metadata uses allowlisted non-secret identity fields; credentials and raw endpoint URLs must not enter persisted metadata or execution fingerprints.
- LLM call auditing is per run. Token usage comes from API usage data; context limits come from response/runtime/model configuration, never inferred from display names.
- Document/row concurrency and prompt-slice concurrency remain distinct desired maxima；PR E Shared `ExecutionBudget` 提供第三個 process-local leaf execution hard ceiling。
- Reduction v1 is incremental: source-agnostic reducers/controllers/checkpoints precede collection manifests and source adapters. Reduction rounds are not business Stages.
- `ReducerResult.changed` remains reducer-local observation. D1 hierarchical decisions use Unicode character counts with target → max rounds → stall precedence.
- Completed checkpoint JSON is the commit marker. Caller-owned deterministic execution identity participates in run keys and compatibility checks.

## Recent Changes

### 2026-09-20 Reduction Engine PR D2

- Production hierarchical reduction reuses only `TokenizerWrapper`, `PromptGenerator`, and `call_llm_api()`; it must never call `process_prompt_and_merge()` or combine recursively.
- `round_task` is applied through a D2-local attribute view that delegates reads to the base context and keeps all writes local. `copy.copy()` is prohibited for this boundary because slot-based row overlays may share their mutable override dictionary. Partial runtime workspaces are disposable; D1 completed checkpoints remain authoritative.
- Post-initial text outputs follow the same caller-owned preparation contract as round 1: preserve content and append a newline only when one is absent before handing items to `ConcatTextReducer`.
- The versioned adapter fingerprint includes prompt/template, task context, tokenizer cut, model/generation, max-token, think, and mock semantics. It excludes secrets, credentials, raw endpoint URLs, paths, PIDs, timestamps, randomness, and object identity.
- One D2 map round always performs the existing ordered two-pass TODO dispatch (`allow_to_retry=True`, then `False`) before incomplete-work validation. Retry passes do not increment the D1 round index. The runtime contract is v2 because context isolation and newline preparation changed output/execution semantics; D1 checkpoint format remains unchanged.
- Hierarchical JSON, Shared ExecutionBudget, collection aggregation, composite/semantic reducers, and ReductionStage remain out of scope.

### 2026-09-19 Reduction Engine PR D1

- Hierarchical text convergence uses Python Unicode character count. Round 1 has no stall comparison; `ReducerResult.changed` is not a controller input.
- Payload is atomically written before checkpoint metadata. Corrupt/incompatible committed chains fail explicitly; orphan payloads may be rebuilt.
- Checkpoint callers must provide a deterministic execution fingerprint covering external round semantics.

### 2026-09-19 Reduction Engine PR C

- Reduction is explicit opt-in, strict, and mutually exclusive with legacy `merge_slices=true`. Single-pass keeps three profiles and existing deep-merge caller defaults.
- Explicit reducer output is authoritative and bypasses legacy post-reduction JSON processing; JSON repair precedes explicit JSON reduction when necessary.

### 2026-08-20 to 2026-08-26 writeback integrity

- Audited slice merge output is the authoritative source-field writeback payload. Merge audit is emitted once per completed item even when transient sink retries recompute it.
- Output-profile schema errors are typed terminal attempts for the current run; transport failures remain retryable. Structured `Event.consequence` is rejected rather than coerced.
- ES mapping/parsing HTTP 400 responses are terminal for an unchanged payload. Existing documents are not silently rewritten.

### 2026-07-17 to 2026-07-23 runtime operations

- Windows legacy multiprocessing overlap uses short reap then targeted thread fallback, without changing the normal non-Windows path.
- ES prefetch defaults off for LLM-heavy workloads. Prompt slice parallelism is separately configurable from document/row parallelism.
- LLM audit uses runtime/API metadata and Ollama active context where available; it does not guess context from model names.

## Archived History

- `decisions.md-20260920-013654.md` — complete pre-compaction decision history through PR D2.
- Earlier archive references contained in that snapshot remain authoritative for older details.

## 2026-09-20 Reduction Engine PR E

- Preserve three distinct concepts: row/doc desired parallelism, slice desired parallelism, and one shared hard leaf-capacity ceiling. Compatibility capacity derives from the maximum configured desired width so a long document is not reduced from 8 slices to `ctx.n_process=2`.
- Use a `threading.Condition` partial-grant lease rather than another scheduler. Leaf executors alone retain permits; orchestration threads are only count-capped, which avoids nested synchronous deadlock.
- Keep the budget private on the root runtime context and let existing overlays delegate to it. Missing budgets preserve legacy external/test caller behavior rather than creating unrelated child budgets.
- Do not include operational concurrency in D2 execution identity. No cross-process/global coordinator and no PR F+ executable/manifest/reducer work is introduced.

## 2026-09-20 Post-PR-E offline production regression boundary

- Deterministic doubles remain at actual external boundaries: localhost HTTP implements `/v1/chat/completions`, while in-memory ES replaces only `helpers.scan` and `helpers.bulk`. Production `PromptAPIPipeline`/`CallLLMAPI`, `SQLiteAdapter`, `SqlSink`, `ElasticsearchAdapter`, `ESSink`, and `CSVSink` remain exercised.
- `e2e` is separate from `live_llm` and is not conditional on GPU credentials. PR F remains unstarted.
