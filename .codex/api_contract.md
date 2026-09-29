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
