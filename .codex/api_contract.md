# api contract

## Current Summary

### Root reduction configuration

- Root `reduction` is opt-in and strictly accepts `enabled`, `profile`, `controller`, `options`, `controller_options`, and `runtime`. Explicit reduction is incompatible with `merge_slices=true`; absence or disabled reduction preserves legacy behavior.
- Controllers are `single_pass`, `fixed_rounds`, and `adaptive_hierarchical`. Hierarchical controllers require `profile: concat_text`, strict controller options and nonblank `runtime.round_task`.
- Canonical reducer profiles are `concat_text`, `concat_json_list`, `legacy_json_deep_merge`, `dedup`, `group`, `entity_union`, `rank`, `top_k`, `composite`, `semantic_llm`, and `structured_relational`. Detailed aliases/examples live in `docs/usage/reduction_engine_v1.md`.
- `execution_budget_capacity`, when configured, is a positive integer process-local hard ceiling for leaf work. Budget capacity is operational and excluded from semantic identity.

### Hierarchical checkpoints and execution identity

- `reduce_hierarchical_text()` consumes prepared text, deterministic controller policy and a narrow next-round callback. Completed checkpoint JSON is the commit marker; corrupt/incompatible committed chains fail closed.
- Checkpointed execution requires deterministic semantic identity. Effective task/prompt semantics, tokenizer/input-cut and model-generation semantics intentionally influence the fingerprint hash; plaintext prompts, credentials, raw endpoint URLs, paths, PIDs and other operational values are not persisted as fingerprint metadata.
- Fixed/adaptive hierarchical production execution uses the prompt-aware tokenizer/render/LLM boundary and never recursively calls business-stage/combine orchestration.

### ReductionStage and bounded nesting

- `ReductionStage` defaults to `failure_policy.mode=require_all`. `allow_partial` additionally accepts strict `min_success_count` and `min_success_ratio`; failed members never enter reducers and only `ExecutionError` is recoverable.
- `ExecutionCancelled` is never a recoverable member failure. Programmer/system faults such as `TypeError`, `AssertionError`, and `MemoryError` remain outside the partial-success channel.
- `ExecutionNestingState` hard-limits v1 to one nested ReductionStage boundary and at most four active PipelineRef names. Cycles/depth overflow fail closed.
- Nested ReductionStage executables reject semantic/composite-semantic child reducers. `TokenizerInputPreparer` and `TokenizerRoundPreparer` use production prompt-aware preflight where available.
- One checkpointed `ReductionStageExecutable` instance serializes complete child-stage executions conservatively; the lock is operational and excluded from semantic identity.

### Collection and aggregate APIs

- Python collection APIs expose immutable `LogicalWorkUnit`, `CollectionManifest`, SQL/ES collection adapters, manifest persistence, `AggregateOutput`, and idempotent aggregate sinks. There is no general collection YAML surface.
- Caller-supplied member ordering is authoritative and fingerprinted. Aggregate sinks reject conflicting lineage; existing ES documents require complete matching aggregate lineage before replacement.
- Complete `AggregateOutput` mapping preserves lineage for aggregate-of-aggregates use.
- Reduction v1.1 Python-only read conveniences: `AggregateOutput.lineage_mapping()`, `extract_aggregate_lineage(AggregateOutput | mapping)`, and `same_aggregate_lineage(left, right)`. Each projection contains only version/aggregate ID/collection ID/manifest fingerprint/output key and validates exact version, format, and ID derivation; malformed/inconsistent mappings raise rather than pretending to compare. A lineage match does not establish payload equality, original manifest authenticity or persisted freshness. Canonical `to_mapping()` remains the sole payload contract; SQL/ES sink authority is unchanged.

### Persisted reuse and semantic freshness

- SQL/ES persisted destination results are the v1 cross-run reuse authority; runtime workspaces are not a reusable result cache.
- Persisted semantic processing identity is opt-in. SQL uses `semantic_freshness.execution_fingerprint` plus a required nonconflicting `processing_identity_column`; ES uses `rerun.execution_fingerprint`.
- `execution_fingerprint: auto` derives identity from effective Executable semantics. Omitting the option leaves no expected identity bound and legacy completeness/rerun rules continue to govern reuse.
- Discovery and pre-dispatch/completion recheck share destination-specific freshness semantics. Recheck diagnostics are bounded and payload-free.

### Task-specific final quality/coverage hook

- `ReductionStage` accepts an optional Python-only `quality_hook`; root YAML and the strict ReductionStage config parser do not expose a generic quality schema.
- A hook implements `evaluate(payload, context, metrics, provenance) -> QualityAssessment` plus `fingerprint_metadata(context)` and a nonblank `contract_version`.
- `QualityAssessment` contains only `accepted: bool`, safe lowercase metric keys with finite bool/int/float values, and safe lowercase warning codes. It does not persist source/prompt/output payloads.
- Accepted assessments are nested under `ReductionStageResult.metrics["quality"]` and summarized payload-free in `audit["quality"]`. Rejected assessments raise `QualityCheckRejectedError`; ordinary hook execution failures raise `QualityCheckError`.
- Hook semantic metadata enters the stage execution fingerprint only when a hook is configured; no-hook stage fingerprints remain unchanged.
- The hook runs once against the final stage result after single-pass or hierarchical reduction. It is an application extension point, not a scorer registry or generic evaluation platform.

### Per-run LLM token/context audit

- API-reported `input_tokens`, `output_tokens`, `total_tokens` and derived `context_usage_ratio` remain the authoritative runtime usage metrics when `token_usage_source=llm_api_usage`; failed/unreported calls must not be treated as synthetic zero-token usage.
- Each actual LLM request emits at most one audit row. The row is written only after request post-processing/persistence settles; if a successful API response is followed by a local failure, the single row is `ok=NO` while retaining that response's API usage/latency instead of emitting a success+failure pair.
- Prompt generation may additionally record `task_text_tokens`, `template_tokens`, `rendered_prompt_tokens`, and `prompt_component_token_source`. These are local tokenizer observability estimates, not billing/runtime usage authority.
- `rendered_prompt_tokens` is counted after the same runtime user-content finalization used by `CallLLMAPI()` (including model-specific suffixes such as Qwen `/no_think`). `template_tokens` is the non-task-text finalized prompt overhead estimate (`rendered_prompt_tokens - task_text_tokens`, floored at zero). Missing component metadata stays blank rather than being guessed.
- Prompt-component handoff is numeric-only and stored outside the TODO/RUNNING queue so queue claiming cannot dispatch metadata files as prompts. No source text, rendered prompt, credentials, or model output is copied into the handoff metadata.
- Windows GUI distribution statistics read the current run's append-only audit CSV. `elapsed_seconds` is exposed as Slice latency only for filesystem-backed rows with a nonblank `prompt_file`; direct repair calls remain in overall audit totals but are excluded from the slice-latency distribution. GUI state does not participate in execution semantics or fingerprints.

### Cancellation and observability

- Production cancellation is cooperative. It stops new scheduling and semantic continuation but does not hard-kill an already-running external request; already-running deterministic safe-drain work may complete.
- Canonical production Reduction events/counters are payload-free. Observer, tags and cancellation state are operational and excluded from semantic fingerprints.

### Retention

- Root `reduction_retention` is a separate frozen operational policy and defaults to disabled.
- Defaults: terminal checkpoint 14 days, incomplete checkpoint 30 days, transient runtime 24 hours, `cleanup_transient_on_success=true`, 100 delete entries, 1 GiB delete bytes and 10,000 scanned entries per sweep.
- Unknown keys/types and invalid TTL/bounds fail strictly. Incomplete TTL cannot be shorter than terminal TTL. `dry_run=true` performs bounded discovery/validation/classification/planning without mutation.
- Only L3-owned marked artifacts are eligible. Legacy unmarked artifacts, final outputs, persisted SQL/ES results, manifests, aggregates, stage artifacts and logs are outside GC ownership.
- After the first deletion entry/byte budget exhaustion, validation/classification/counters continue for later candidates while deletion stays disabled for the rest of that sweep.
- Successful hierarchical final write with `cleanup_transient_on_success=true` invokes immediate eligible transient cleanup using effective transient TTL zero; set it false to retain successful runtime workspaces for the configured transient TTL.

### ES metadata safety

- Persisted model metadata is allowlisted. Credential-like keys, actual endpoint URLs, API keys/tokens/passwords/private keys and raw model specs must not be written into ES metadata.

## Recent Changes

### 2026-10-08 LLM token/context GUI observability

- Extended the per-run audit contract with local prompt-component token estimates while preserving API usage as authoritative token/context usage.
- Added a default-collapsed Windows GUI distribution surface driven from the append-only audit CSV, including per-slice LLM latency P50/P95/max.

### 2026-10-06 v1.1 final quality/coverage hook

- Added the narrow Python-only final-result quality policy contract described above; it is explicit, fingerprinted, payload-minimizing, and outside root YAML.

### 2026-10-06 Closure documentation corrections

- Clarified that persisted semantic processing identity is opt-in and that prompt semantics influence the hash without persisting plaintext prompts.
- Clarified default immediate cleanup behavior for successful transient runtime artifacts.

### 2026-10-06 L3 reporting corrective

- PR #201 introduced the run-local deletion-budget latch and added regressions for later malformed tombstones and smaller artifacts encountered after byte-budget exhaustion.

### 2026-10-04 L2/L3 contracts

- Added explicit partial-success/cancellation taxonomy, production cancellation/observer contracts and safe retention/GC contracts.

### 2026-10-02 to 2026-10-03 K2/L1 contracts

- Added bounded nesting, prompt-aware input preparation, persisted processing identity and SQL/ES freshness/recheck contracts.

## Archived History

- `.codex/archive/api_contract.md-20261006-134200.md` — complete pre-compaction API/contract history through PR #200 head `39177737486a372f38e9b6d81563d6f14327459a`.

### 2026-10-12 audit GUI throughput extension (pending review)

- Optional per-call audit columns: `cached_input_tokens` (nullable), `cached_input_token_source` (either `provider_usage` or blank), and `stage_identity` (safe stage name or `single_stage`). No prompt/output payload is added to the audit handoff. Provider cache usage accepts an explicit zero but never infers a zero when metadata is absent.
- Existing `processing_tps` remains API-total-based historical telemetry. GUI-only `total_tok_per_s` is derived from API input+output divided by strictly positive slice elapsed. GUI-only `effective_tok_per_s_est` uses provider-reported cached input when valid, otherwise a conservative, stage-isolated heuristic after repeated stable template-size evidence; estimate samples and provider samples are counted separately and absent evidence remains unknown.

### 2026-10-19 ES multidim_event_json metadata normalization (PR #216 pending)
- Strict ES multidim output_profile still requires exactly article_date_iso (date or null) and article_date_precision (day/month/year/unknown) as a coherent pair; null requires unknown and non-null cannot have unknown. For multidim sliced merge only, source-consistent pairs are selected atomically under existing left/right policy. No inference of publication date from Event_Timeline or signature/event dates.
- On strict profile normalization only, exact top-level keys coverage/novelty/impact/credibility/importance_score may be moved losslessly into importance; a conflicting nested duplicate is an error, and allowed value type is integer or null, not bool/float/string. Unexpected other fields still fail closed. Generic JSON / alternate output profiles are unchanged.
- Existing audit and writeback metadata behavior, Event/event_ids referential integrity, pending status and original Success retention are unchanged.


### 2026-10-19 ES per-row bulk acknowledgement (proposed new PR)
- `ESSink.write_main()` / `write_flatten()` can enqueue bulk updates without sending them immediately. In the Row Merger path, `ESSink.confirm_writeback()` explicitly drains that buffer and propagates bulk failures before source input, successful slices, or pending/completion bookkeeping can be finalized.
- For an acknowledged ES bulk, search-based pending discovery may still require an index refresh; the confirmation contract does not force refresh or prove an entire batch is complete.
- Other sink types retain their previous behavior; this change must be validated by exact-head CI and external ES readback before release.


### 2026-10-20 run-scoped processing-quality JSONL v1 (PR #218)
- Per-run sibling of `llm_call_audit_<run_id>.csv`: `processing_quality_events_<run_id>.jsonl`.
- Every record: `schema_version=1`, UUID `event_id`, UTC `ts`, `run_id`, `event`, `scope`, `code`, `outcome`, `document_id`, `slice_id`. Event families: `slice_json_validation`, `slice_json_repair`, `document_schema_rejected`, `document_writeback_confirmed`. No raw prompts, outputs, secrets or exception bodies.
- GUI percentages: first-pass invalid / completed JSON validation attempts; repair successful / completed repair attempts; final schema pending (distinct document IDs with rejection but without later confirmation) / distinct documents with writeback decision. Unknown denominator is not shown as 0%.

### 2026-10-20 PR #218 acknowledgment caveat
- `document_writeback_confirmed` is emitted only for sinks implementing successful `confirm_writeback()`; currently ES bulk acknowledgement (not ES refresh/readback). Excel/CSV/SQl without this explicit handshake do not contribute a confirmed writeback count. Do not interpret missing confirmation events as failed documents or a batch-wide success percentage.

### 2026-10-20 offline CLI quality report contract (separate PR)
- `python -m czjLLM.cli_tools.processing_quality_report --audit-path <llm_call_audit_run.csv>` reads the matching JSONL, or `--audit-dir <directory> [--limit 1..100]` reads bounded sorted run history; optional `--output <report.json>` is atomic and refuses JSONL as a destination.
- Report `report_version=1` contains observed `QualityAccumulator` aggregate metrics only, with `state`, `sample_advisories`, `incomplete_or_concurrent_append`; never exports raw event/document IDs or silently converts missing denominators to 0%. Recovered schema does not remain failed. No cross-run aggregate percentage, and explicit acknowledgment only (currently ES) does not imply ES readback.

- Report `skipped_corrupt_complete_lines` and `state=degraded_corrupt_lines` explicitly warn whenever newline-terminated UTF-8/JSON decoding fails; partial last lines remain excluded until complete. Counters do not count corrupt records as valid attempts.

- Existing `QualityTailReader` now exposes `skipped_corrupt_lines` counting both undecodable complete JSONL and valid-JSON records rejected by the quality accumulator (except valid duplicate IDs). Incremental input generation detection uses inode plus bounded consumed head/tail consistency, not size alone. Existing GUI `poll() -> (changed, stats)` remains unchanged.

- Quality event contracts are per-event code allowlists. JSON validation only accepts JSON_VALID / JSON_SYNTAX_INVALID; JSON repair only repair succeeded/failed; document schema rejection only SCHEMA_*; document writeback confirmation only WRITEBACK_CONFIRMED. Emitters reject mismatched scope/code; readers degrade on unsupported event/code combinations, wrong supplied scope, missing document identity, or non-integer schema_version. Missing scope in earlier synthetic fixtures remains accepted for compatibility.

- Duplicate `event_id` is accepted as a harmless idempotent replay only when the canonical JSON record is identical; conflicting reuse counts as a degraded complete line. Reader reset publishes `changed=True` even when the new file is empty/invalid, preserving GUI update contract. Nonstring event/code values are rejected rather than raising TypeError.

- Quality JSONL reader rejects nonstandard NaN/±Infinity JSON tokens; accumulator requires non-whitespace event IDs and document IDs for document events. Canonical event signatures reject non-finite Python float extras by allow_nan=False. Malformed full lines increase skipped_corrupt_complete_lines and do not contribute to quality metrics.

- The optional legacy `scope` field is compatible ONLY when genuinely omitted. If supplied, `scope` must be the exact `slice` or `document` value derived from the event. Explicit JSON null, blank string, or mismatched scope degrades the report and never enters its denominator.

- A recursion-depth failure while decoding a complete JSONL line counts as a rejected corrupt complete line; the reader continues with subsequent lines instead of aborting a whole report or keeping a stale GUI snapshot. GUI document error label is now 'LLM 文件結構異常（待處理）', describing observed post-merge output validation failures, not Elasticsearch mapping errors.


### 2026-10-23 quality JSONL Consumer incident schema (new PR, unmerged)

- Existing version 1 schema additionally accepts `event=consumer_orchestration_failure` with `scope=run` and allowlisted codes `CONSUMER_ROUND_TIMEOUT`, `CONSUMER_ROUND_EXCEPTION`, `CONSUMER_TERMINATED`. Invalid code/scope combinations fail closed; there is no source, prompt, document, or slice ID in this event.
- `QualityAccumulator.snapshot()` adds integer `consumer_orchestration_failure_events`; no percentage or denominator is introduced. Existing JSON validation/repair and document decision rates are unchanged. Retries can produce multiple events.


### 2026-10-23 PR #222 P2 run-event privacy correction (pending validation)

- For `consumer_orchestration_failure`, `emit_quality_event()` explicitly rejects nonempty or non-string `document_id` and `slice_id` rather than relying on the one internal caller. The reader/accumulator also refuses any nonempty/non-string identity in version-1 run events, including previously emitted/tampered complete JSONL rows. Omitted fields and exact empty strings remain compatible. No other event type's identity contract changes.

### 2026-10-23 Producer operational quality extension (P2 PR proposal)

- Existing per-run `processing_quality_events_<run_id>.jsonl` schema v1 admits one new `event=producer_operational_failure`, `scope=run`, `outcome=observed` with fixed codes: `PRODUCER_SCHEDULE_EXCEPTION`, `PRODUCER_BACKPRESSURE_EXCEPTION`, `PRODUCER_FUTURE_EXCEPTION`. The write and read boundaries reject nonempty/null `document_id` or `slice_id`; events do not include exception text, input/prompt text, URLs, secrets, paths or PKs.
- `QualityAccumulator.snapshot()` adds `producer_operational_failure_events` and per-code entries under existing `error_codes`. Numerators are observed caught exceptions only and are never folded into slice JSON attempts, repair attempts, documents decided/schema-pending, or LLM call failures. Existing schema_version and API signatures remain unchanged; missing count is handled as zero in GUI. Real worker/Stage failures and rate denominators remain outside the contract.
- Added Producer production catch-site regression gate to Hosted Linux offline E2E; exact-head Codex and CI acceptance pending.

### 2026-10-23 PR #224 Producer schedule event semantic clarification (pending review)

- `PRODUCER_SCHEDULE_EXCEPTION` means **only** a non-cancellation exception raised directly by the `schedule_one_row()` call. It does **not** cover preceding `mark_running()`, `record_adjustment(mark_running_before_dispatch)`, or no-op `mark_not_running()/record_adjustment()` bookkeeping failures; those are separate operational failure sources and must not be silently conflated with the scheduler code. The outer existing catch/release behavior remains unchanged. No payload/PK/exception body is included in the emitted run event.

### 2026-10-23 Stage orchestration quality events (P2 PR proposed; Hosted acceptance pending)

- Extend Quality schema v1 with `event=stage_orchestration_failure`, `scope=run`, `outcome=observed`, fixed codes `STAGE_PREPARE_EXCEPTION` (Stage task resolution/input preparation exception) and `STAGE_RUNNER_EXCEPTION` (escaped exception from actual Stage Runner call, after legacy signature fallback where needed). The public writer and strict reader reject non-empty, null, or otherwise non-string document/slice IDs for run events; original exception, stage/chunk identity, model endpoint, prompt/output, file paths and secrets are not included in JSONL.
- Add `stage_orchestration_failure_events` to `QualityAccumulator.snapshot`, with codes in existing `error_codes`. Not a distinct failed document count, provider request failure, full worker exception taxonomy or a rate denominator. An `ExecutionCancelled`, normal `{ok:false}` or successful 2-arg Runner fallback does not emit an incident. The original Runner/Stage exception remains authoritative and propagates.
