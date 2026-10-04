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

## 2026-09-20 PR #185 live safety corrective

- Reachability never grants mutation permission. Live fixtures check explicit opt-in before configuration or client construction, validate dedicated namespaces before connecting, and clean only UUID-owned records.
- `requirements-e2e.txt` is a dependency-light test install surface aligned with production pins; it excludes model-training dependencies and does not change production dependency semantics.

## 2026-09-20 PR #185 final acceptance boundaries

- Direct adapter/sink and direct live-service CRUD tests are classified as focused boundary/service smokes, not application orchestration proof. Offline `handle_data_mode` and TXT handler tests are the authoritative production-path gate.
- Production concurrency acceptance creates real TODO files and enters `call_llm_api`; tests must not manually lease permits around direct `PromptAPIPipeline` calls.

## 2026-09-20 PR #185 E2E dependency convergence

- `requirements-e2e.txt` follows imports reached by production paths under `tests/e2e`, not the full development/training environment. Collection is explicitly path-scoped before marker selection so unrelated tests cannot impose dependencies on the offline gate.

## 2026-09-20 Remove stale ES_utils dependency

- ES client creation belongs to `resolve_es_connection` plus `ElasticsearchAdapter.connect`; predefined and per-writeback mapping application belongs to `ensure_schemas_es` plus `ElasticsearchAdapter.apply_mapping_file`. The missing `utils.ES_utils` import had no caller and is not a compatibility API or pip dependency.

## 2026-09-21 Preserve hierarchical item workspaces after combine

- The combine boundary owns legacy cleanup, but checkpoint-backed hierarchical execution requires the original prepared Success inputs and item-local D1/D2 state for stable run-key lookup and terminal resume. Cleanup is therefore skipped only for enabled normalized controllers `fixed_rounds` and `adaptive_hierarchical`.
- Checkpoint location, identity, format, atomic commit semantics, runtime layout, and execution fingerprints are unchanged. No partial GC policy is introduced.

## 2026-09-24 Reduction Engine PR F immutable collection contracts

- Preserve three separate identifiers: `collection_id` names the stable aggregate namespace, each `LogicalWorkUnit.logical_id` names one member, and `CollectionManifest.fingerprint` identifies the full ordered semantic contract. Duplicate unit IDs fail rather than deduplicate.
- Preserve caller-supplied order and include it in the fingerprint; core code must not guess SQL/ES ordering or silently sort. Future adapters own their source-specific canonical ordering and identity mapping.
- Payload is identity-relevant because changing reducer-facing work changes the collection contract. Unit and collection provenance are also identity-relevant, but accept only JSON-compatible, non-secret, non-runtime metadata. Nested state is recursively frozen rather than relying on `frozen=True` alone.
- Persist exact canonical fields and validate fingerprints on reconstruction. Unknown/missing fields, incompatible versions, malformed IDs, unsupported values, duplicates, and corruption fail explicitly; no identity generation, schema repair, ordering repair, or fingerprint repair is allowed.
- The collection manifest is not a business-stage manifest or execution state. PR F adds no Executable/Stage abstraction and no PR G+ adapter, sink, routing, or reducer behavior.

## 2026-09-24 Reduction Engine PR F identity safety corrective

- Reuse the existing credential-text and JWT patterns for both logical and collection IDs. Do not apply provenance key substring checks to free-form identity values: obvious credential syntax is rejected, while benign semantic IDs containing words such as `secretariat`, dates, `host`, or `session` remain permitted.
- Stability is a caller/source-adapter contract rather than a heuristic classifier. Core does not generate identities from random/runtime state; provenance retains separate recursive structural rejection of known nondeterministic keys.
- Keep manifest v1 because this is a pre-merge validation tightening. Fingerprint schema and algorithm remain unchanged.

## 2026-09-24 Reduction Engine PR G

- Membership is resolved once. Retry consumes the immutable persisted manifest and never silently re-queries; a new explicit snapshot is the only way to include source changes.
- SQL stable IDs are lossless-enough type-tagged scalar strings (`str:`, `int:`, `bool:`, deterministic float hex, bytes hex); NULL/empty/unsupported values fail. ES defaults to `_id`, with an explicit source path override. Explicit versions are safe provenance only and are never synthesized from snapshot time.
- Adapters sort by configured stable order values and logical-ID tie-breaker, or logical ID alone. Group IDs are base collection namespace plus canonical normalized-JSON group hash; explanatory values remain provenance and NULL group values fail.
- Aggregate contract v1 keeps collection namespace, manifest snapshot, and output namespace distinct. SQLite uses a PK plus `ON CONFLICT DO UPDATE`, after a lineage-conflict check inside `BEGIN IMMEDIATE`; ES uses deterministic `_id` with `update` and `doc_as_upsert=true`.
- Aggregate sinks expect an Output-Profile-validated final payload; they do not introduce validation. Row Merger and existing source-row sinks remain separate. PR H composite reducers are intentionally not implemented.

## 2026-09-29 PR G pre-merge correctness fixes

- Explicit ordering means semantic scalar ordering, not string/repr ordering. Heterogeneous scalar types use a documented total type order, while integers and finite floats share their numeric domain.
- Source field vocabulary must remain data. Ordered field/value records solve reserved provenance-name collisions without weakening PR F validation.
- ES custom identity normalization is strict and type-tagged. ES lineage integrity belongs in the atomic scripted update itself rather than a race-prone client GET check.
- Aggregate output contract stays at version `1`; identity inputs remain contract version, collection ID, manifest fingerprint, and output key. Payload remains excluded.

## 2026-09-29 ES create detection corrective

- Application-field presence is not a creation signal. Scripted upsert branches on Elasticsearch's `ctx.op == 'create'`; every pre-existing deterministic ID, including manually indexed or legacy incomplete documents, must pass full lineage validation and is never silently repaired.

## 2026-09-30 Reduction Engine PR H

- Deterministic means strict JSON validation and canonical sorted-key JSON equality, never fuzzy/case-folded/LLM/embedding semantics. Missing paths and malformed entities/scores fail rather than being guessed or discarded.
- First occurrence is authoritative for exact dedup and entity union. Ranking uses Python's stable numeric sort without payload-hash tie breakers. Composite audit contains bounded per-step metadata, never intermediate payloads.
- Configured reducers are fresh instances built centrally; registry entries remain discovery/default metadata and are never mutated. PR I/J/K/L remain unimplemented.
- Public reducer construction is a fail-closed boundary, not merely a convenience behind strict YAML parsing. Registry prototypes are permitted only for discovery and must not execute successfully while unconfigured. Path grammar is shared with config validation and rejects wholly whitespace components without stripping caller keys.
- Canonical reducer equality normalizes generic mappings and list/tuple containers to detached JSON-native dict/list structures before encoding. Do not require callers to thaw `LogicalWorkUnit.payload`, and do not mutate or replace retained first-occurrence values.

## 2026-09-30 Reduction Engine PR I

- Semantic v1 performs one call per invocation: no child pool, recursion, truncation, fan-out, or fallback. Ordered inputs use six-digit boundaries; non-strings use PR H canonical JSON.
- Production reuses `PromptGenerator`, `TokenizerWrapper`, `PromptAPIPipeline`, shared leaf `ExecutionBudget`, and existing LLM audit through a non-mutating task overlay.
- Scope is single-pass and composite-final only. PR J relational contracts, PR K nesting/stages, and PR L cache/retention remain unimplemented.

## 2026-09-30 PR #189 response-cleanup corrective

- Do not map `think_mode` to `include_think`: model thinking instructions and application-output cleanup are separate existing contracts. Semantic v1 keeps prompt rendering aware of `think_mode` and always uses the production-default think-tag cleanup. Zero evidence is not a valid semantic consolidation input.

## 2026-10-01 Reduction Engine PR J

- Relational v1 is structural, not semantic: every record owns an independent local namespace, so equal local IDs across records always receive distinct first-appearance canonical IDs. No fuzzy, text, embedding, or LLM consolidation occurs.
- Use an explicit two-pass algorithm so references may precede entity collections in mapping order. Preserve only configured relationship semantics; unrelated strings and top-level business fields are never conflict-resolved or merged.
- Complete remap provenance is mandatory, while audit stays bounded to a canonical-JSON SHA-256 fingerprint and counts. This is why `structured_relational` is rejected inside current composite execution rather than weakening provenance.
- PR F/G manifest and aggregate contracts remain version `1`; aggregate ID derivation, adapters, and sinks are unchanged. PR I semantic behavior and D1/D2 hierarchical/checkpoint contracts are unchanged. PR K/L remain unimplemented.

## 2026-10-01 PR #190 strict configuration corrective

- Reject canonical-prefix language overlap at construction/config parsing rather than waiting for cardinality-dependent post-remap collisions. Keep the existing post-remap global collision check as defense in depth and keep the generated-ID format unchanged.
- Treat configured entity and reference field endpoints as exclusive ownership claims: duplicates within either category and exact cross-category conflicts are invalid. This removes multiple-writer ambiguity without banning legitimate distinct fields in one collection.

## 2026-10-01 Reduction Engine PR K1 scope decision

- Resolve the former PR-K nesting question conservatively: K1 proves direct PipelineRef-to-ordinary-stage-pipeline execution only. `ReductionStageExecutable`, ref chains, depth/stack guards, cycles, and raw-document nested reduction belong exclusively to K2.
- Execution fingerprints contain task/pipeline/renderer/model-generation and round-preparer semantics, but exclude credentials, endpoint URLs, runtime reprs, timestamps, thread/process identity, and budget capacity.
- Initial worker-map results are intentionally not checkpoint-cached or reused in K1; PR L owns member cache/retention policy.

## 2026-10-01 PR #191 review corrective

- Checkpoint safety requires fingerprinting effective rather than requested task semantics. Tokenizer `InputCutLen` and `model_spec_name` are semantic because they can change leaf acceptance and hierarchical chunk boundaries; budget capacity and credentials remain scheduling/secret data and are excluded.
- Wrapper metadata is namespaced rather than flattened: PipelineRef retains target audit, and single-pass ReductionStage retains reducer audit/provenance/metrics. Hierarchical D1 metadata contracts are not redesigned.

## 2026-10-01 PR #191 final K1 corrective

- Generic read-only mappings are first-class task pools. Nested task specs and `InputCutLen` share one bounded chain traversal; repeated keys terminate identity/preflight resolution without adding PipelineRef graph-cycle machinery.

## 2026-10-02 PR #192 K2 corrective

- Preserve K1 final-prompt fail-closed behavior and make both K2 tokenizer preparers delegate to that exact production rendering/tokenization boundary. Deterministically refine source content only; fail when prompt overhead or a smallest usable fragment cannot fit.
- Version prompt-aware preparation semantics in native preparer fingerprints; exclude source/prompt content and operational/secret values.
- Serialize one checkpointed nested executable instance conservatively rather than changing D1 checkpoint schema, run keys, atomic ordering, D2 identity, or historical artifacts. Finer run-key coordination remains future work, not this K2 corrective.
- Revert the unrelated K2 documentation compaction; keep only narrow append-only project status updates.

## 2026-10-02 Reduction Engine PR L1

- Persisted SQL/ES outputs remain reuse authority; no duplicate member-result file cache is introduced.
- Semantic execution fingerprint extends destination freshness and is derived only from the established Executable metadata/normalized fingerprint machinery.
- Structured recheck observability is part of L1. The legacy skip log remains alongside the bounded canonical JSONL event stream.
- Optional caching for intentionally transient K2 outputs is deferred to L3 pending production evidence; K2 transient execution remains valid and non-persisted.

## 2026-10-02 PR #193 L1 corrective

- Auto identity must be derived from the effective existing Executable contract, never from a separately maintained task/prompt hash. Bind once before discovery and reuse exactly through writeback.
- An explicitly configured SQL identity column is safe schema metadata, but collision is a configuration error; silent renaming or payload overwrite is forbidden.
- GUI snapshots replace a fixed status surface. Routine throttled updates do not append log history; only the error transition is emphasized.

## 2026-10-03 PR #193 final L1 corrective

- Prefer correctness over ES query optimization for Python-only required-output semantics. Broaden only explicit validation jobs and retain optimized discovery elsewhere.
- Never fall back from a missing diagnostic job identifier to executable task/prompt content. Both canonical and legacy logs share the safe identifier helper.
