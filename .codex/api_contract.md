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

## Current Processing Quality contracts

The following sections describe the accepted main implementation through PR #239. Historical review/merge placeholders were superseded; see exact archived snapshot for original chronology.

### run-scoped processing-quality JSONL v1 (PR #218)
- Per-run sibling of `llm_call_audit_<run_id>.csv`: `processing_quality_events_<run_id>.jsonl`.
- Every record: `schema_version=1`, UUID `event_id`, UTC `ts`, `run_id`, `event`, `scope`, `code`, `outcome`, `document_id`, `slice_id`. Event families: `slice_json_validation`, `slice_json_repair`, `document_schema_rejected`, `document_writeback_confirmed`. No raw prompts, outputs, secrets or exception bodies.
- GUI percentages: first-pass invalid / completed JSON validation attempts; repair successful / completed repair attempts; final schema pending (distinct document IDs with rejection but without later confirmation) / distinct documents with writeback decision. Unknown denominator is not shown as 0%.

### offline CLI quality report contract (separate PR)
- `python -m czjLLM.cli_tools.processing_quality_report --audit-path <llm_call_audit_run.csv>` reads the matching JSONL, or `--audit-dir <directory> [--limit 1..100]` reads bounded sorted run history; optional `--output <report.json>` is atomic and refuses JSONL as a destination.
- Report `report_version=1` contains observed `QualityAccumulator` aggregate metrics only, with `state`, `sample_advisories`, `incomplete_or_concurrent_append`; never exports raw event/document IDs or silently converts missing denominators to 0%. Recovered schema does not remain failed. No cross-run aggregate percentage, and explicit acknowledgment only (currently ES) does not imply ES readback.

- Report `skipped_corrupt_complete_lines` and `state=degraded_corrupt_lines` explicitly warn whenever newline-terminated UTF-8/JSON decoding fails; partial last lines remain excluded until complete. Counters do not count corrupt records as valid attempts.

- Existing `QualityTailReader` now exposes `skipped_corrupt_lines` counting both undecodable complete JSONL and valid-JSON records rejected by the quality accumulator (except valid duplicate IDs). Incremental input generation detection uses inode plus bounded consumed head/tail consistency, not size alone. Existing GUI `poll() -> (changed, stats)` remains unchanged.

- Quality event contracts are per-event code allowlists. JSON validation only accepts JSON_VALID / JSON_SYNTAX_INVALID; JSON repair only repair succeeded/failed; document schema rejection only SCHEMA_*; document writeback confirmation only WRITEBACK_CONFIRMED. Emitters reject mismatched scope/code; readers degrade on unsupported event/code combinations, wrong supplied scope, missing document identity, or non-integer schema_version. Missing scope in earlier synthetic fixtures remains accepted for compatibility.

- Duplicate `event_id` is accepted as a harmless idempotent replay only when the canonical JSON record is identical; conflicting reuse counts as a degraded complete line. Reader reset publishes `changed=True` even when the new file is empty/invalid, preserving GUI update contract. Nonstring event/code values are rejected rather than raising TypeError.

- Quality JSONL reader rejects nonstandard NaN/±Infinity JSON tokens; accumulator requires non-whitespace event IDs and document IDs for document events. Canonical event signatures reject non-finite Python float extras by allow_nan=False. Malformed full lines increase skipped_corrupt_complete_lines and do not contribute to quality metrics.

- The optional legacy `scope` field is compatible ONLY when genuinely omitted. If supplied, `scope` must be the exact `slice` or `document` value derived from the event. Explicit JSON null, blank string, or mismatched scope degrades the report and never enters its denominator.

- A recursion-depth failure while decoding a complete JSONL line counts as a rejected corrupt complete line; the reader continues with subsequent lines instead of aborting a whole report or keeping a stale GUI snapshot. GUI document error label is now 'LLM 文件結構異常（待處理）', describing observed post-merge output validation failures, not Elasticsearch mapping errors.

### quality JSONL Consumer incident schema
- Existing version 1 schema additionally accepts `event=consumer_orchestration_failure` with `scope=run` and allowlisted codes `CONSUMER_ROUND_TIMEOUT`, `CONSUMER_ROUND_EXCEPTION`, `CONSUMER_TERMINATED`. Invalid code/scope combinations fail closed; there is no source, prompt, document, or slice ID in this event.
- `QualityAccumulator.snapshot()` adds integer `consumer_orchestration_failure_events`; no percentage or denominator is introduced. Existing JSON validation/repair and document decision rates are unchanged. Retries can produce multiple events.

### Producer operational quality extension (P2 PR proposal)
- Existing per-run `processing_quality_events_<run_id>.jsonl` schema v1 admits one new `event=producer_operational_failure`, `scope=run`, `outcome=observed` with fixed codes: `PRODUCER_SCHEDULE_EXCEPTION`, `PRODUCER_BACKPRESSURE_EXCEPTION`, `PRODUCER_FUTURE_EXCEPTION`. The write and read boundaries reject nonempty/null `document_id` or `slice_id`; events do not include exception text, input/prompt text, URLs, secrets, paths or PKs.
- `QualityAccumulator.snapshot()` adds `producer_operational_failure_events` and per-code entries under existing `error_codes`. Numerators are observed caught exceptions only and are never folded into slice JSON attempts, repair attempts, documents decided/schema-pending, or LLM call failures. Existing schema_version and API signatures remain unchanged; missing count is handled as zero in GUI. Real worker/Stage failures and rate denominators remain outside the contract.
- Added Producer production catch-site regression gate to Hosted Linux offline E2E; exact-head Codex and CI acceptance pending.

### Stage orchestration quality events
- Extend Quality schema v1 with `event=stage_orchestration_failure`, `scope=run`, `outcome=observed`, fixed codes `STAGE_PREPARE_EXCEPTION` (Stage task resolution/input preparation exception) and `STAGE_RUNNER_EXCEPTION` (escaped exception from actual Stage Runner call, after legacy signature fallback where needed). The public writer and strict reader reject non-empty, null, or otherwise non-string document/slice IDs for run events; original exception, stage/chunk identity, model endpoint, prompt/output, file paths and secrets are not included in JSONL.
- Add `stage_orchestration_failure_events` to `QualityAccumulator.snapshot`, with codes in existing `error_codes`. Not a distinct failed document count, provider request failure, full worker exception taxonomy or a rate denominator. An `ExecutionCancelled`, normal `{ok:false}` or successful 2-arg Runner fallback does not emit an incident. The original Runner/Stage exception remains authoritative and propagates.

### leaf Worker quality phase event extension
- Quality JSONL schema_version=1 adds `event=worker_phase_failure`, `scope=run`, `outcome=observed` and allowlisted `code` values: `WORKER_PRECALL_EXCEPTION`, `WORKER_LLM_CALL_EXCEPTION`, `WORKER_RESPONSE_EXCEPTION`, `WORKER_PERSIST_EXCEPTION`. Both writer and reader reject non-empty/non-string document_id and slice_id in these run events. No request, slice, stage, document identity, raw exception, URL, prompt or model response fields are emitted.
- `QualityAccumulator.snapshot()` adds `worker_phase_failure_events`; codes appear in existing `error_codes`. These are exception observations only (no denominator) and never imply a distinct failed LLM call/document or failure rate. The existing `PromptAPIPipeline.proc` return dict, CSV request audit, cancellation handling, and mock results are unchanged.

### Worker SDK typed subtype extension
- Existing `worker_phase_failure` `scope=run` allowlist gains `WORKER_LLM_TIMEOUT_EXCEPTION`, `WORKER_LLM_CONNECTION_EXCEPTION`, `WORKER_LLM_RATE_LIMIT_EXCEPTION`, `WORKER_LLM_HTTP_SERVER_EXCEPTION`, `WORKER_LLM_HTTP_CLIENT_EXCEPTION`, `WORKER_LLM_RESPONSE_VALIDATION_EXCEPTION`. Events still have no document/slice/stage IDs, prompt, endpoint, credentials, raw error or response; writer/reader reject misplaced identities and codes.
- One caught leaf Worker error produces at most one `worker_phase_failure` quality record; its existing `worker_phase_failure_events` count and old request CSV format/exception return remain unchanged. Unknown SDK/local errors retain `WORKER_LLM_CALL_EXCEPTION`. Only typed SDK exceptions / status (4xx/5xx) and known wrapped direct causes qualify for refinement.

### read-only incident family diagnostics report
- Existing `processing_quality_report.py` `report_for_audit(audit_path, *, incident_family=None)`, `report_history(audit_dir, *, limit=20, incident_family=None)`, and `summarize_quality_stream(path, *, incident_family=None)` gain an optional fixed allowlist run-only event-family focus. CLI adds `--incident-family {consumer_orchestration_failure,row_merger_retryable_failure,producer_operational_failure,stage_orchestration_failure,worker_phase_failure}` for `--audit-path` or `--audit-dir`. Unknown or document/slice family is an error, never a silent zero.
- Each existing `run` report gains additive `incident_diagnostics`: `scope=run`, denominator explanation, `focus_family`, `observed_run_incident_events`, and `families[event]={observed_events,codes,share_of_observed_incidents_pct}` plus low-sample advisory. Code keys are accepted fixed JSONL error enums with count > 0 only; family groups come from the same source-of-truth event/scope mapping as strict JSONL parser. A focused report still includes full unfiltered `metrics` and a denominator from **all** run-only incidents, so filtered counts do not imply a rate of failed documents.
- Empty observed incident denominator produces `share_of_observed_incidents_pct=null`, not 0%; counts can be zero. Repeated catch sites may describe one logical failure. Corrupt complete lines and incomplete tail retain existing degraded/incomplete status; no raw JSONL, event IDs, document/slice IDs, URLs, prompts or exception text in new diagnostics. No change to `report_version=1`, legacy result fields, producer CSV or JSONL schema.

### manual JSONL segment rotation stage 1
- `czjLLM.cli_tools.processing_quality_rotate --audit-path llm_call_audit_<run>.csv --confirm-stopped [--max-segments N]`: explicit maintenance command returning only `mode=manual_quality_rotation`, `rotated: bool` and `archived_segments: int`. Refuses missing acknowledgment, malformed audit filename, incomplete active final record, symlink, gap, collision or exhausted bounded archives. No auto timer or deletion.
- `rotate_quality_event_stream(audit_path, *, max_segments=64)` produces `processing_quality_events_<run>.jsonl.seg-00000001` etc using the existing writer lock. New emits still append to `processing_quality_events_<run>.jsonl`.
- Existing `summarize_quality_stream`, `report_for_audit`, `report_history` replay archived segments plus optional active using one accumulator; allow archive-only runs; reject discontinuous archive indexes and distinguish `degraded_incomplete_archive`. Existing `run.metrics` and `incident_diagnostics` remain consistent with one logical run. Additive `archived_segments` integer field; no alteration to JSONL event version, `report_version=1`, request CSV or GUI controls.

### quality archive consistency manifest v1
- Sidecar derived from active path: `processing_quality_events_<run>.jsonl.manifest.json`; JSON v1 contains exactly `schema_version:1`, `segments: [{sequence:1..N, bytes:int, sha256:64-lowercase-hex}, ...]`, `ledger_sha256` (canonical segments JSON hash). Maximum 64 shards and 24 KiB metadata; no raw event identifiers, documents, model addresses or secrets. This is self-consistency, NOT an authenticated chain/signature.
- New CLI `python -m czjLLM.cli_tools.processing_quality_manifest --audit-path ...` reports only `mode=quality_archive_manifest`, `status` and `sealed_segments`. One-time opt-in legacy baseline uses `--initialize --confirm-stopped`, cannot overwrite an existing baseline; no in-place archive modifications. The existing manual rotate CLI remains unchanged; after initial sealing it validates and extends the manifest atomically under the same writer lock.
- Offline single-run/history report `run.archive_integrity={status:verified|unsealed_legacy|not_applicable,sealed_segments:int}` is additive, `report_version=1` unchanged. Verified mismatch, missing archive, invalid sidecar, symlink or concurrent metadata mutation raises `ValueError` (fail closed); archive-only history with missing sealed shards must still surface error. `state=observed` alone does not prove sealed consistency; `unsealed_legacy` warns on unprotected history. No legacy CSV, quality event JSONL schema, GUI or provider contract modifications.

### GUI quality cumulative stream snapshot
- `QualityRunTailReader(path).poll() -> (changed:bool, stats:dict)` reuses all `QualityAccumulator.snapshot()` keys, plus `quality_stream_status` (observed/not_initialized/unsealed_legacy/incomplete_tail/degraded_corrupt_lines), `quality_archived_segments:int`, `quality_archive_integrity:string` (verified/unsealed_legacy/not_applicable), `quality_skipped_corrupt_lines:int`. The per-run reader maintains accumulated distinct document and event ID state across physical archive boundaries, and only replays full archives on actual generation changes. The meaning of fixed event percentages does not change.
- GUI worker translates unsafe/invalid archive, active-file or manifest I/O states to aggregate-only `quality_stream_status=unverified` and an explicit unknown-statistics message; no stale prior green state, raw exception text, URLs, run IDs, source documents, payload or local paths. No change to JSONL writer event schema or `report_version=1`. No user control to trigger rotation from GUI.

### GUI read-side safety-budget contract
- `QualityAccumulator(*, max_events: int|None=None, max_identity_chars: int|None=None)` and `QualityTailReader(path='', *, accumulator=None, max_line_bytes: int|None=None)` remain unlimited by default. Positive (non-bool) integer budgets may be supplied by read-side callers; crossing a budget raises `QualityCapacityExceeded(ValueError)`, without accepting the over-limit event or advancing the committed JSONL byte offset. `empty_copy()` preserves limits on an active generation reset.
- `QualityRunTailReader(path='', *, max_events=50000, max_identity_chars=4000000, max_line_bytes=65536)` enforces the same finite budget across sealed and legacy archived segments plus active JSONL. GUI-only `quality_stream_status=capacity_exceeded` is distinct from `unverified`; GUI publishes no partial metrics on either status. No event schema, persisted file, manifest format, or offline `report_version=1` change; archived events remain losslessly available to the separate uncapped offline report.

### unchanged GUI over-cap generation behavior
- `QualityRunTailReader.poll()` may raise `QualityCapacityExceeded` immediately after metadata checks on subsequent polls of the same previously failed generation. This is intentional; its public contract continues to provide **no partial snapshot** while over-cap. Archive/Manifest/active identity changes invalidate this fast path, and switching to a new reader/path resets it. Original offline report and event output contracts unchanged.

### optional offline report SQLite identity spill
- `summarize_quality_stream(path, *, incident_family=None, disk_backed=False)`, `report_for_audit(..., disk_backed=False)`, `report_history(..., disk_backed=False)`, and CLI `--disk-backed` enable ephemeral local SQLite exact event/document identity retention. Default False retains prior API behavior.
- Results use the **same** `report_version=1` single/history payload, diagnostics, percentages, safety statuses and integrity validation; raw IDs and temporary DB paths must not enter the JSON report. OS-managed private temporary SQLite stores are destroyed in normal/error cleanup; no persistent data/index contract.

### offline quality benchmark CLI
- `python -m czjLLM.cli_tools.processing_quality_benchmark --audit-path <llm_call_audit_*.csv> [--repetitions 1..5] [--timeout 1..3600]` is an opt-in read-only CLI. JSON stdout contains `benchmark_version=1`, `mode=offline_quality_single_run`, `parity=matching_complete_report_sha256`, `report_sha256`, `repetitions`, `measurements.{memory,sqlite}` and `measurement_notes`; each measurement exposes sample count, median elapsed seconds, median traced Python peak bytes, nullable OS high-water RSS bytes and nullable SQLite main temp DB final bytes.
- The tool does not change offline report v1 JSON/CLI output or JSONL lifecycle. Its private stdin-only worker protocol is **not** a stable public API. Source/payload/identity and private paths must not be printed or persisted.

### benchmark source-generation fail-closed extension
- Existing `benchmark_quality_run(...)` and CLI/JSON output shapes remain unchanged. Input now must contain a physical quality stream (active or valid numbered archive), not merely a CSV-shaped audit filename. Before/after every child sample, the benchmark validates unchanged canonical JSONL/shard/manifest path metadata; altered generations raise sanitized `ValueError` and CLI exits 2 without emitting performance JSON.
- Inputs must be regular non-symlink files; no claim of synchronized/atomic content hashing. Existing `report_sha256` parity check remains independent and required.

### Win32 native benchmark memory semantics
- Existing `benchmark_quality_run()` and CLI JSON contract remain unchanged. On Windows, `median_peak_process_rss_bytes` now intends to report native PSAPI `PROCESS_MEMORY_COUNTERS.PeakWorkingSetSize` in bytes. The field remains null when the API fails, rather than making up a metric or deriving it from `tracemalloc`. On Linux/macOS original `ru_maxrss` interpretation is unchanged.
- This Windows statistic is a peak resident **working set**, not private committed/virtual bytes, a zero-cost in-report memory peak, or a hard RSS guarantee. Only intra-host comparisons on stable inputs are valid. Windows self-hosted tests not yet run.

### optional benchmark subprocess wall-time metric
- The opt-in `benchmark_quality_run()`/CLI still returns `benchmark_version=1` and the prior result keys; each `measurements.{memory,sqlite}` gains additive numeric `median_subprocess_wall_seconds` (`>=0`) derived **only** from parent monotonic-clock timing of the child `subprocess.run()`. Existing `median_seconds` remains inner report-call runtime and is unchanged. No report-v1 JSON, worker stdin protocol, source-files or archives contract changes.
- This value includes process spawn/import, IPC and child exit but excludes parent metadata integrity guards and entire CLI time. It is not performance superiority, a worker-selected metric or a production SLA.

### benchmark numeric validity at private worker boundary
- Opt-in benchmark CLI/JSON public shape stays `benchmark_version=1`; every numeric summary metric must serialize as finite, standard JSON (never NaN/Infinity). Parent rejects nonstandard worker tokens `NaN`/`Infinity`/`-Infinity`, float exponent overflow, non-finite/negative worker report wall time, non-integer/negative traced bytes, and invalid parent-observed subprocess wall time. On failure, no partial benchmark result is emitted; CLI exits 2 with fixed sanitized argparse error and no raw identities, private paths, stdout or child exception details.
- Private worker protocol remains internal; invalid data fails closed rather than substituted with zero or inferred values. Existing report-version 1 and SHA256/source-generation parity contracts unchanged.
## Current Elasticsearch multidimensional Event / writeback contracts (accepted)
- The strict ES `multidim_event` output profile at `czjLLM/es_mode/output_profiles/multidim_event.py` requires the **paired** top-level `article_date_iso` and `article_date_precision` fields. `article_date_iso` is a valid calendar `YYYY-MM-DD` or null; precision is exactly `day`, `month`, `year` or `unknown`. Null requires `unknown`, a non-null date forbids `unknown`, month precision requires day `01`, and year precision requires `YYYY-01-01`. Missing/mismatched pair fails strict validation; no date may be inferred from event `time_raw`. Keep source article publication date distinct from timeline/event dates.
- `czjLLM/utilities/slice_merge.py` selects the article date **as an atomic (date, precision) pair from one slice**, using the configured conflict policy; never combine date from one slice with precision from another, substitute an event date, or silently invent validity when all complete pairs are invalid. The strict output profile must still reject an invalid preserved pair.
- The current Event model uses `Event: list[object]` with unique nonblank `event_id`; linked `Person`, `Involved_Parties`, `Impact`, `Event_Timeline`, and evidence records use `event_ids` that must refer to existing Event IDs. Legacy single-object Event and old timeline date shapes are not supported. Preserve original raw source/Success artifacts when strict schema or references fail rather than silently acknowledging writeback.
- `czjLLM/es_mode/runtime/sinks/es_sink.py` `write_main()`/`write_flatten()` can **enqueue** buffered ES bulk actions: enqueue/dispatch alone does not mean an acknowledged durable write. `confirm_writeback()` flushes pending bulk operations before Row Merger marks a row complete or deletes its original Success/source artifacts. On an exception, `discard_unacknowledged_writeback()` clears queued unacknowledged actions and preserved source/result artifacts remain replay authority; some idempotent writes may already have applied. Search visibility/refresh is separate from acknowledgement and needs independent readback in operator E2E.
- These constraints are active even though older review chronology lives in the exact archived `.codex/api_contract.md` snapshot. Do not weaken validation, fill unknown values by guesswork, or declare ES writeback confirmed without actual acknowledgement.

## Current strict ES importance normalization contract (accepted)
- In `czjLLM/es_mode/output_profiles/multidim_event.py::_normalize_flat_importance_fields()`, **only** the five exact documented top-level metric keys `coverage`, `novelty`, `impact`, `credibility`, `importance_score` can be **losslessly moved** into the nested `importance` object. Values must be an `integer` (excluding booleans) or `null`; floating, string and boolean scores fail strict type checks.
- If the same score exists nested and top-level, validate **both** representations and reject conflicting values, including malformed nested values that compare equal in Python (e.g. `True == 1`). Never silently overwrite, recompute a score or accept unrelated top-level fields. Unknown fields still fail the strict output profile; this narrow repair does **not** change generic JSON handling or other profiles.
- The move is a shape normalization only, not a license to infer article publication metadata, source provenance or ES bulk acknowledgement.

## Current cache-aware audit and GUI throughput contract
- `czjLLM/utilities/llm_call_audit.py::append_llm_call_audit()` keeps API-provided `input_tokens`, `output_tokens`, `total_tokens` and original `processing_tps` fields. Optional `cached_input_tokens` is **nullable** (an absent provider signal stays blank/unknown, never a synthetic zero); `cached_input_token_source` equals `provider_usage` only for supported actual provider usage. A provider-reported **zero cached input** is valid and distinct from missing data. No estimated cache hit is written back to the authoritative provider audit.
- Prompt-component audit may carry a safe `stage_identity` (or a separately recognized `single_stage` where appropriate) and local `prompt_component_token_source`, not raw prompts, output payloads or sensitive task metadata. The GUI groups heuristic template-history comparisons by **model, endpoint, task, YAML stage identity and tokenizer/source**; different stages must never share a cacheable-template estimate.
- `czjLLM/job_manager/win_gui.py` derives GUI-only `total_tok_per_s = (API input_tokens + output_tokens) / elapsed_seconds` for real prompt-file slice requests with authoritative `token_usage_source=llm_api_usage`, finite nonnegative counts and strictly positive elapsed. Existing `processing_tps` is historical API-total telemetry with different fallback/collection semantics and is **not** silently redefined by either GUI distribution.
- GUI `effective_tok_per_s_est` uses `(input_tokens - cached_input_tokens + output_tokens) / elapsed_seconds` **only** for valid `provider_usage` cache values (including explicit 0). Otherwise, an explicitly labeled `heuristic` estimate is permitted only after **at least two prior near-stable template-size samples from the same model/endpoint/task/stage/source**, with a conservative maximum 50% discount of that stable template floor. Missing stage identity, component source, token counts or stable history means *no effective-throughput sample*, not zero cache reuse or an inferred provider hit. Provider and heuristic sample counts are kept separate.
- `total_tok_per_s` and `effective_tok_per_s_est` are **request-level observed elapsed-throughput proxies** including network/queue/time-to-first-token overhead, not pure GPU/kernel generation rates or a true billed-token cache saving guarantee. A heuristic remains an estimate even when plotted in the same default-collapsed GUI distribution.

## Archived History
- `.codex/archive/api_contract.md-20261027-213700.md` — **exact pre-compaction** snapshot (Git blob `b1ef36b488496a83059bf82123c391b719cd3aab`) preserving dated decisions, prior review statuses, PR SHA/CI evidence and older archival references; consult only when tracing history.
- Earlier archives referenced inside this snapshot remain unchanged; no history was deleted.
- Active summary reconciled with GitHub `main` `46b7c7290417421a6dc09e114f82c1066ce0179d` after user-authorized PR #239 merge and Linux postmerge `offline-e2e` success; Windows runner jobs remain queued/operator-deferred.

## 2026-10-28 offline quality report protected export destination (accepted PR #241)
- The existing `python -m czjLLM.cli_tools.processing_quality_report` `--audit-path`/`--audit-dir` modes, `report_version=1` JSON schema, optional `--disk-backed` ephemeral backend and legitimate `--output quality_summary.json` remain unchanged.
- Before source replay/temporary SQLite creation, a requested `--output` must have a `.json` suffix, must not be a symlink, and must **never** occupy the reserved `processing_quality_events_*.jsonl.manifest.json` integrity ledger namespace (case-insensitive for Windows), whether ledger exists or not and regardless of which run was requested. Fail as a fixed path-free argparse error with no partial JSON output and no report/ledger writes. Normal standalone JSON output remains atomically replaceable.
- Output control also applies to the accepted PR #242 `llm_failure_report` failure-taxonomy CLI: it must reject canonical `processing_quality_events_*.jsonl.manifest.json` anywhere (even another audit directory), before private CSV replay, while retaining same-source-dir audit artifact bans, ordinary JSON output and unchanged report-v1 denominators. These are inadvertent-overwrite guards only, not race-free authentication, manifest CLI modifications, online rotation or automatic pruning. Pending independent time-window extension for the same read-only CLI: `--since` inclusive and `--before` exclusive strict naive producer-local `YYYY-MM-DDTHH:MM:SS`, fail closed on any missing/invalid timestamp or malformed row in scoped snapshots, never compare across host time zones as UTC. Unfiltered `report_version=1` schema unchanged; filtered reports add `time_window` (clock/bounds/since/before) and `excluded_by_time_window` per run only. Denominator remains observed call rows, not document/unique retry identities. Pending new audit-record schema: freshly created `llm_call_audit_<run>.csv`/XLSX adds trailing opaque UUID4 `audit_record_id` (per logged row, not provider request/dispatch/retry identity); preexisting exact previous header remains unmodified in shape, unsupported headers fail closed, and filtered/unfiltered failure report v1/denominators never count or export UUIDs. Pending Worker-boundary extension: new audit CSV/XLSX adds trailing `worker_call_id` after `audit_record_id`, minted by `PromptAPIPipeline.proc` immediately before actual `CallLLMAPI`; validated optional caller-provided 32-char lowercase hex, blank when no known Worker invocation, two prior full CSV headers continue unchanged width. Distinct Worker calls are not proven HTTP attempts or retry families; read-only v1 reports never export either ID. Pending next audit observation: a new trailing `call_llm_api_returned` CSV/XLSX field is explicit YES/NO/unknown blank, captured immediately after real `CallLLMAPI` returns or raises; non-null observation requires valid Worker-call ID. This only describes wrapper return, not HTTP acknowledgement, final local `ok`, retry lineage or ES sink success. Three previous exact CSV headers remain append-compatible without migration; report v1 and denominators remain unchanged. Pending separate explicit split-lineage journal enhancement: optional opaque 32-char UUID4 `split_family_id` in existing version-1 `_extract_slice_identity/splits/<parent>.txt.json`, with unchanged parent/child SHA256; a bounded digest-verified direct parent/child query returns the group or unknown for old/malformed journals. This is unauthenticated split-intent evidence, not proof of committed children, source document or logical/provider retry. No Worker, CSV/XLSX, report-v1 or sink schema change.

## 2026-10-29 Worker-to-split family audit contract

- New per-run LLM call CSV/XLSX appends trailing `split_family_id`, an optional validated canonical UUIDv4 paired with `worker_call_id` and explicit `call_llm_api_returned`. The Worker supplies it only when actual queued source bytes match the sent content and a persisted two-child SHA256 split-intent journal confirms parent/child/nested provenance after repair. Missing/legacy/malformed proof => blank, not fabricated. Previous four complete CSV headers preserve widths during append and unknown headers still reject. Read-only failure-report v1 observed call-row denominators, quality JSONL, SQL/ES and underlying Worker scheduling unchanged. Does not count SDK HTTP attempts, requeues, completed splits, sink acknowledgements or unique documents.
