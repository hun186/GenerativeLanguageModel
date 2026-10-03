# api contract


---

## 


-

## 2026-08-20 ES model metadata contract

- `<output_col>_meta` 可保存 `model_tag`、`model_name`、`base_url_alias`、`num_ctx`、`temperature`、`model_version` 及既有 pipeline/task tracking fields。
- `base_url_alias` 必須是非敏感 alias，不得以實際 `base_url` 代替。
- `model_spec`、`base_url`、`api_key`、access/auth token、Authorization、password、client secret、private key 等 credential 不得寫入 ES metadata；ES sink 在 writeback boundary 會移除 credential-like keys。

## 2026-09-19 Reduction Engine PR D1 Python contract

- `reduce_hierarchical_text()` 僅接受 prepared text sequence、registered `concat_text` reducer、deterministic controller，以及 `next_round_items(previous_payload, next_round_index)` callback。
- Normal stop reasons 為 `target_reached`、`fixed_rounds_complete`、`max_rounds`、`stalled`；後兩者回傳最後有效 payload 並附 warning。Empty output、reducer failure、checkpoint corruption、checkpoint incompatibility 是不同 error paths。
- 此為 inactive Python seam，不是 production YAML/API contract；production 設定仍僅接受 PR C `single_pass`。

## 2026-09-19 PR D1 checkpoint execution identity corrective

- `reduce_hierarchical_text(..., checkpoint_root=..., execution_fingerprint=...)` requires a non-blank caller-owned execution fingerprint whenever checkpointing is enabled. In-memory execution without `checkpoint_root` does not require it.
- Changing only this identity creates a distinct run key; the value is also persisted and strictly compatibility-validated. Callers must cover external deterministic round-builder and reducer-context semantics without placing secrets in the fingerprint.

## 2026-09-20 Reduction Engine PR D2 production configuration

Hierarchical text reduction is explicitly enabled with one of these strict root configurations:

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
    min_reduction_ratio: 0.10
  runtime:
    round_task: SUMMARY
```

- Hierarchical controllers accept only `concat_text` and require a non-empty `runtime.round_task`; unknown or missing controller/runtime fields are rejected. `single_pass` retains all three PR C profiles/options and rejects hierarchical-only settings rather than silently consuming them.
- Fixed `rounds` is a positive integer. Adaptive target is a non-negative integer, max rounds is a positive integer, and ratio is finite in `[0,1]`. Explicit reduction remains mutually exclusive with `merge_slices=true`.
- Round numbering follows D1: round 1 reduces existing initial map Success items; round 2 is the first new tokenizer/prompt/LLM map cycle.

## 2026-09-20 Reduction Engine PR E execution capacity contract

Production root configuration accepts one optional canonical setting:

```yaml
execution_budget_capacity: 8
```

- The value must be a positive integer; booleans, strings, zero, and negative values are rejected. Precedence is root/run explicit value, model-profile `execution_budget_capacity`, derived maximum of existing positive local process/row/slice settings, then `1`.
- `ExecutionBudget(capacity).lease(requested)` requires a positive integer and yields `1..min(requested, available, capacity)` after blocking without busy-spinning when capacity is exhausted. The granted amount is always returned on scope exit, including exceptions.
- This is a Python runtime/process-local contract, not a serialized business API or distributed coordination contract. Private budget state does not enter persisted configuration or D2 fingerprints.

## 2026-09-24 Reduction Engine PR G Python contracts

- `SQLCollectionQuery(sql, parameters, member_id_field, payload_fields, version_field=None, group_fields=(), order_fields=())` describes an explicit parameterized membership query.
- `SQLCollectionAdapter(adapter, source_alias=...).snapshot(collection_id=..., query=..., window=None)` executes once and returns a deterministic tuple of immutable manifests.
- `ElasticsearchCollectionAdapter(adapter, source_alias=..., scan=None).snapshot(...)` composes a connected production adapter; `_id` is the default identity and transport injection exists only at the external scan seam.
- `CollectionManifestStore.save(path, manifest)` atomically persists canonical mapping; `load(path)` strictly reconstructs and verifies it without source fallback.
- `AggregateOutput(manifest, output_key, payload, provenance=None)` expects a final/validated payload. `derive_aggregate_output_id()` hashes aggregate contract v1, collection ID, manifest fingerprint, and output key.
- `SQLiteAggregateSink.ensure_schema()/upsert(output)` and `ElasticsearchAggregateSink.upsert(output)` are dedicated first-class aggregate persistence APIs.

## 2026-09-29 PR G corrective contract details

- `deterministic_scalar_order_key(value)` orders booleans first, integers/finite floats together by numeric value, strings lexically, then bytes lexically; null, non-finite floats, and structured values fail. Adapters append logical ID as the final tie-breaker.
- Group provenance is `group: [{"field": <source-name>, "value": <source-value>}, ...]` in caller-supplied group-field order. The same ordered data drives group ID hashing.
- A custom ES identity is type-tagged (`str:`, `int:`, `bool:`, `float:`) and rejects empty/null/structured/non-finite values. Default ES `_id` remains its native non-empty string.
- `ElasticsearchAggregateSink.upsert()` uses Elasticsearch 7 `scripted_upsert`; its write-boundary script compares `collection_id`, `manifest_fingerprint`, and `output_key` before replacing document fields.

## 2026-09-29 ES existing-document lineage guard

- Existing aggregate documents must contain identical `aggregate_output_id`, `aggregate_output_contract_version`, `collection_id`, `manifest_fingerprint`, and `output_key`. Missing, null, or different values are conflicts; only `ctx.op == 'create'` bypasses existing-lineage comparison.

## 2026-09-30 PR H deterministic reducer contract

- New v1 canonical profiles and aliases: `dedup` (`deduplicate`, `exact_dedup`), `group` (`group_by`), `entity_union` (`union`, `exact_union`), `rank`, `top_k` (`topk`, `top-k`), and `composite`.
- Options are strict: dedup/entity union accept optional non-empty `key_paths`; group requires non-empty `by`; rank requires `score_path` and optional boolean `descending` (default true); top-k requires positive integer `k`; composite requires non-empty mapping steps shaped exactly as `{profile, options?}`.
- Group payload is an ordered list of `{key: [{path, value}, ...], items: [...]}`. Equality is canonical exact JSON equality; rank accepts finite non-boolean numbers and preserves stable input order for ties.
- Composite allows local profiles only, rejects recursive composite, and is single-pass-only. Parsed paths and steps are recursively detached into tuples and read-only mappings.
- PR #188 corrective: public reducer constructors validate parameter options without depending on input cardinality. Blank or whitespace-only dotted components are invalid without trimming/reinterpretation. The registry may retain metadata prototypes for required-option reducers, but prototype execution fails closed; an empty composite also fails on `reduce()`, and a nested composite fails at construction.
- PR #188 immutable-payload corrective: canonical equality recursively detaches every supported `Mapping` to `dict` and every list/tuple to `list` before sorted-key JSON encoding. This accepts PR F `MappingProxyType`/tuple payloads directly while preserving strict string keys, finite numbers, and unsupported-object rejection.

## 2026-09-30 Reduction `semantic_llm` v1

- Canonical profile `semantic_llm` (alias `semantic`), contract version `1`, single-pass only.
- Strict options schema is exactly `{task: <non-blank string>}`; supplied text is preserved. Model settings, URLs, keys, and generation kwargs are rejected as options.
- Composite permits at most one semantic step and only in final position. Success returns a non-empty string, bounded character/count metrics, and safe task/model/cost observations.
- Missing runtime, invalid input, multi-chunk prompt, failed runtime result, or blank output raises explicitly; no fallback exists.

## 2026-09-30 PR #189 corrective

- `semantic_llm` requires at least one input item; zero items raise `SemanticReducerError` without invoking `SemanticRuntime.execute`.
- `think_mode` remains prompt-rendering context only. Semantic calls preserve `PromptAPIPipeline.include_think=False`, so internal `<think>` content is not part of the reducer payload.

## 2026-10-01 Reduction `structured_relational` v1

- Canonical profile `structured_relational` (alias `relational`), contract version `1`, is top-level `single_pass` only and is rejected in composite and hierarchical configurations.
- Options contain exactly `entity_sets` (required non-empty sequence of `{name, collection_path, id_field, canonical_prefix}`) and `references` (required sequence of `{collection_path, field, target}`); paths use mapping-only dotted traversal and ID/reference fields are direct member keys.
- Each flattened record is a local namespace. Canonical IDs are assigned as `<unique-prefix><1-based entity-set counter>` in record/member first-appearance order; output is detached `list[dict]`, preserving records, members, and unrelated values.
- Result provenance contains complete immutable `id_remap` records (`record_index`, `entity_set`, `local_id`, `canonical_id`). Audit exposes only remap count/fingerprint and spec counts; metrics expose record/entity/reference and rewrite counts.

## 2026-10-01 PR #190 strict relational configuration corrective

- Canonical-prefix namespaces must be pairwise disjoint for the unchanged `<prefix><positive decimal counter>` format. Equal prefixes overlap; a longer prefix also overlaps a shorter prefix when its remaining suffix is ASCII decimal digits beginning with `1`–`9`.
- Entity endpoints `(collection_path, id_field)` and reference endpoints `(collection_path, field)` are each unique. An exact endpoint may not be owned by both categories; the same collection remains valid across distinct fields.

## 2026-10-01 Reduction Engine PR K1 executable contracts

- `Executable.execute(item, ExecutionContext) -> ExecutableResult` is the source-independent worker boundary; result metadata is frozen and distinct from `ReducerResult`. `ExecutionContext` carries only the root runtime, TaskRuntime, local registry, and reducer context.
- K1 exposes `TaskExecutable`, ordinary in-memory `StagePipelineExecutable`, and `PipelineRefExecutable`. A ref may resolve only directly to `StagePipelineExecutable`; nested refs and ReductionStage targets are rejected until K2.
- `ReductionStage` consumes caller-prepared items, supports single-pass or existing hierarchical text reduction, and returns a frozen `ReductionStageResult`. Hierarchical stages require a `RoundPreparer`; the strict `parse_reduction_stage_config` does not require legacy D2 `runtime.round_task`.

## 2026-10-01 PR #191 K1 fingerprint/metadata corrective

- Production task identity now records the effective task specification from the same bound task pool used for rendering, its effective `InputCutLen`, callable source when available, tokenizer/model identity, the complete allowlisted D2 generation settings, mock/think modes, and the fixed `include_think=false` contract.
- `PipelineRefExecutable` preserves target audit under `audit.target`; single-pass `ReductionStage` preserves reducer audit, provenance, and metrics under `reducer` namespaces. `ReductionStageResult` detaches its top-level metadata mappings.

## 2026-10-01 PR #191 final K1 task-pool corrective

- Stage route task resolution accepts any `Mapping`, including detached `MappingProxyType`; absent pools retain global fallback. Production task resolution follows one cycle-safe task-spec chain for both fingerprint semantics and nearest `InputCutLen`.
# 2026-10-02 Reduction Engine PR K2 bounded nesting contract

- `ExecutionContext` adds an immutable `ExecutionNestingState`: nested-reduction depth starts at 0, permits a configured hard-v1 maximum of 0 or 1, and PipelineRef stacks permit 1..4 active names (default 4). Derived contexts are returned for every transition; callers cannot raise either hard limit.
- `PipelineRefExecutable` resolves only `StagePipelineExecutable`, `PipelineRefExecutable`, or `ReductionStageExecutable`. Execution and fingerprint traversal share the same immutable push, self/indirect cycles fail with a bounded ref path, and a fifth active ref fails before target traversal.
- `InputPreparer` exposes `prepare(item, context)` and `fingerprint_metadata(context)`. `IdentityInputPreparer` emits one item; `TokenizerInputPreparer` validates nonblank text and emits ordered chunks using the effective production `InputCutLen` without an LLM call or budget lease.
- `ReductionStageExecutable` accepts one `ReductionStage` whose worker is a direct task or named PipelineRef plus one input preparer. It enters exactly one guarded nested boundary, rejects semantic/composite-semantic child reducers, and preserves child audit/provenance/metrics under bounded namespaces.
- `parse_reduction_stage_executable_config()` is strict (`type`, `input_preparer`, `stage` only), delegates `stage` validation to `parse_reduction_stage_config()`, and does not own or populate a registry.
- `ReductionStage.fingerprint_metadata()` is the canonical semantic identity surface. It covers stage contract, reducer profile/actual contract/options, controller/options, worker, and optional round preparer while excluding concurrency, budget, checkpoint path, endpoints, credentials, and runtime identity.

## 2026-10-02 PR #192 prompt-aware preparation corrective

- `ProductionTaskRuntime.preflight_task_content(task=, content=)` renders and tokenizes through the exact leaf preflight without an LLM call or budget lease. `prepare_content_chunks(task=, content=)` deterministically refines source-only fragments until each passes that preflight, preserves content/order, and fails if prompt overhead or a smallest usable fragment cannot fit.
- `TokenizerInputPreparer` and `TokenizerRoundPreparer` delegate to that production surface when available; their fingerprints include `production-prompt-aware-split-v1`. Dependency-light custom runtimes retain the deterministic raw-tokenizer fallback.
- One checkpointed `ReductionStageExecutable` instance serializes complete child-stage executions with an operational lock excluded from semantic identity. Non-checkpointed execution is not serialized.

## 2026-10-02 PR L1 contracts

- `ProcessingIdentity(contract_version="reduction-processing-identity-v1", execution_fingerprint=<full hash>)` is safe persisted identity; `executable_semantic_fingerprint(executable, context)` hashes normalized `Executable.fingerprint_metadata(context)`.
- `PendingDecision(pending, reason, diagnostics)` is additive. Existing `is_row_pending(...) -> bool` remains; SQL/ES expose explanatory checking without raw payloads.
- SQL strict freshness opts in with `semantic_freshness.execution_fingerprint` and explicit `semantic_freshness.processing_identity_column`. Without it, all output columns nonempty remains complete.
- ES opts in with `rerun.execution_fingerprint`, stored as `<configured meta field>.execution_fingerprint`; all existing rerun criteria remain cumulative.
- Recheck JSONL defaults to `logs/pending_recheck_events.jsonl`, bounded to 30 MB. Fingerprints in logs are display-only 12-character prefixes.

## 2026-10-02 PR #193 L1 corrective contracts

- `execution_fingerprint: auto` resolves through `executable_semantic_fingerprint(effective_executable, ExecutionContext)` once before pending discovery. Literal fingerprints remain supported as external overrides.
- Strict SQL rejects processing-identity collisions with primary/input/output/writeback/expanded destinations and explicitly prepares the identity column as text.
- ES configured semantic metadata is strict: missing model/pipeline metadata yields `missing_meta`; mismatches yield `model_tag_mismatch` or `pipeline_hash_mismatch`; execution identity retains its dedicated missing/mismatch reasons.

## 2026-10-03 PR #193 final L1 corrective contracts

- `_requires_python_freshness_scan(output_cols)` activates conservative single-index scanning for active required-output checks. The Python `PendingDecision` contract is authoritative; initial candidates must be a safe superset of Python-pending documents.
- `task_json` in canonical and legacy recheck logs is a bounded safe job identifier: explicit config basename, simple pipeline name, or `unknown`. Raw task/prompt text is not an identifier source.
