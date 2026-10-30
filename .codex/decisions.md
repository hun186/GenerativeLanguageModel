# Architecture Decisions

## Current Summary

- `combine_utils.py` remains the compatibility facade for Success discovery/output placement/final writes; Row Merger remains writeback coordination and Output Profile remains final strict schema validation.
- Reduction is explicit opt-in and source-agnostic. Reduction rounds are not business Stages.
- Persisted SQL/ES destination results remain the sole cross-run member-result reuse authority. A v1.1 evaluation explicitly deferred any transient semantic/member cache until measured duplicate-call evidence justifies it; no persistent/global second cache may become an authority.
- Semantic processing identity is opt-in at persisted destination boundaries. `auto` derives from effective Executable semantics; prompt/task semantics affect the hash while plaintext prompts, secrets and operational state are excluded from persisted fingerprint metadata.
- Caller-supplied collection ordering and immutable manifest identity are authoritative; aggregate sinks reject conflicting lineage.
- Bounded composition is deliberate: one nested ReductionStage level, at most four active PipelineRef names, explicit cycle/depth failure, and no nested semantic reducer.
- `require_all` remains the compatibility default. Partial success is explicit opt-in and only `ExecutionError` is recoverable; cancellation and programmer/system faults propagate.
- Operator cancellation is cooperative safe-drain. Producer cancellation and worker teardown are distinct; already-running HTTP calls are not forcibly killed.
- Cancellation/observer/retention/concurrency settings are operational and excluded from semantic fingerprints.
- A configured task-specific quality hook is semantic because it can accept/reject the final result; its contract/config metadata therefore participates in the stage execution fingerprint. No-hook fingerprints remain unchanged.
- Recheck Status and Reduction Status are separate observability surfaces; diagnostic JSONL is bounded and payload-free. LLM token/context distributions are a third default-collapsed GUI observability surface sourced from the run audit CSV, not a new execution authority.
- Filesystem GC is disabled by default, ownership-based, bounded and conservative. Unmarked pre-L3 artifacts are never adopted; malformed state fails closed.
- Committed checkpoints are resume authority, runtime round directories are reconstructable, and L1 persisted SQL/ES output remains cross-run reuse authority.
- After deletion budget exhaustion, classification/reporting continues but deletion cannot resume later in the same sweep.
- `cleanup_transient_on_success=true` is the default post-success fast path; retaining successful runtime workspaces for the transient TTL requires disabling that option.
- Reduction Engine v1 A–L is complete. The L3 audit corrective merged at `91e39503c8e84d17752f9d26a23ff6b34db75b9e`, and PR #200 documentation/release closure merged at verified `main` `99d79676b16b7fed54f9cf6e701441db79846cea`.

## Current Processing Quality design decisions

The following sections describe the accepted main implementation through PR #239. Historical review/merge placeholders were superseded; see exact archived snapshot for original chronology.

### Producer operational observability boundary (P2 PR proposal)
- Instrument catch-site exceptions rather than parse console messages or infer failure from a schedule returning zero. Mark operational events run-scoped with fixed enums, no row/stage identity or source content. Do not change cancellation, pending-row skip, ordinary schedule-noop semantics or multistage Future behavior.
- Existing per-run JSONL writer and reader remain the only event authority; GUI is a projection. No new persistent store or request/document failure-rate denominator. Stage Worker and lifecycle/retention remain separate so this PR's scope stays reviewable.

### leaf Worker execution site classification decision
- Use a fixed enum set by control flow before the external model call, while running the call, after its successful return, or while persisting Success/identity. Avoid user-provided exception messages, class-name guessing, model URLs or any stage/input/prompt ID as an event field. Do not label every call-site exception a provider failure.
- A run-scoped leaf Worker phase event and a request CSV entry can both describe one failure; do not aggregate them into distinct failed documents. Keep the historical caught-error return, CSV row finalization, mock-only behavior and cancellation handling unchanged. Emitter failure is best effort and cannot replace original Worker results.

### SDK failure subtype policy
- Reuse one existing `worker_phase_failure` run-only event rather than issuing a second SDK event per caught exception. Only refine the previously established `WORKER_LLM_CALL_EXCEPTION` phase, using SDK exception classes and verified `APIStatusError.status_code`; do not infer from localized error text, URLs, regular expressions or arbitrary `RuntimeError`.
- Distinguish 429 vs HTTP 5xx vs 4xx (with generic fallback); preserve original `CallLLMAPI` exception/return and legacy CSV. A classifier failure is best effort and must never mask the original Worker failure. Categorize mechanisms as evidence, not remote-model blame.

### incident drilldown scope policy
- Deliver fixed-code, run-only **read-only reporting** first: the JSONL `QualityTailReader` remains sole authority for valid/duplicate events and corrupt line status. Filter accepted counts from the same mapping as the emitter/parser, never parse exception text, URLs or source IDs and never reread raw source to extract "examples".
- CLI family focus is an allowlisted *presentation projection*; retain unfiltered metric counters and the denominator of all observed run-scoped incidents. Show unknown percent on zero denominator and low-sample advisory. No new persistent store, event schema or cross-run aggregation; lifecycle/rotation and operator-specific privacy/redaction improvements remain future work.

### JSONL lifecycle phase 1 no-delete boundary
- Start with **opt-in manual rotation after operator stops writers/readers**, not online timer or automatic retention. Reuse the producer's cross-process append lock, same-directory atomic rename and consecutive numbered archives without rewriting or deleting any accepted event; reject partial last records, gaps and archive budget exhaustion.
- Extend existing offline report with shared-accumulator replay instead of summing per-file aggregates (which would double-count event IDs and lose document reject→confirmed recovery). Keep GUI single-live-file view as a disclosed limitation. Only introduce destructive retention and real live readers with separate consistency/manifest protocol and independently tested rollback/partial-failure semantics.

### archive integrity ledger trust boundary
- Choose manual opt-in trust-on-first-use SHA-256 sidecar over automatic migration of legacy archives; avoid falsely asserting past integrity. Hash immutable numbered archives only, not concurrently growing active JSONL. Retain original append lock and no-delete rotation; write metadata via same-directory atomic replace with fsynced payload, roll back rename on publication errors where safe.
- Verify sealed archive count and hashes both before and after offline multi-shard replay. A ledger mismatch fails closed rather than reset or inferred successful migration; retain existing strict event schema, duplicate ID and per-document recovery semantics. Explicitly distinguish self-consistency from authenticated evidence, defer signed manifests, crash recovery, automated retention and GUI continuity.

### incremental GUI multi-segment reader policy
- Rebuild one validated cumulative quality accumulator on archive/manifest/active generation changes, but tail only complete active JSONL lines during stable generations to avoid rescanning potentially large archives each GUI poll. Keep privacy-minimal and scope-correct event-id de-dup/document recovery; avoid adding slice and document percentages together.
- Treat invalid sealed history or missing known active without documented rotation as an unavailable snapshot, **not** the previous apparently valid numbers. Report unsealed/partial/corrupt completeness warnings separately and do not change the safety boundary of manual stopped-producer rotation. Run the reader outside Tk only; defer Windows visual E2E, cryptographically anchored integrity, automatic pruning and safe online rotation.

### bounded GUI event retention fail-closed policy
- Avoid silently approximating document schema rates or losing dedup consistency by pruning seen event IDs and document sets. Introduce explicit optional read-side budgets enforced **before** accepted-event state mutation and before advancing JSONL offsets. GUI alone uses finite threshold defaults, reports capacity-exceeded instead of partial numbers, and keeps archived JSONL and Manifest untouched. Offline report retains the original full audit contract.
- Bound single JSONL record length before `json.loads` in GUI readers; do not reclassify an oversized unknown event as merely a harmless invalid record. This restricts decoder spikes but is not a byte-precise process memory cap. Crash-safe bounded-memory checkpoints and guaranteed retention retirement need separate protocol and tests.

### unchanged over-cap GUI poll cache
- Do not repeat full JSONL/archive verification after a known `QualityCapacityExceeded` if all archived, manifest and active file-generation metadata were unchanged during the failed attempt. Memoize only the failure generation, not input content or a partial accumulator result. Continue raising a distinct unavailable capacity error; retry only when generation changes or a different run reader is created. Retain prior observed archive cardinality so unsealed shard disappearance after over-cap first load cannot be mistaken for a newly healthy smaller run. Bounded stat polling is not cryptographic authentication.

### offline temporary SQLite identity spill
- First relieve large offline report identity-map growth via an **explicit opt-in, temporary, exact SQLite** backend; do not silently change the uncapped original accumulator or the already budgeted GUI reader. Reuse existing event/code validation and aggregate counters; store exact identities rather than lossy hashes if claiming exact dedup. Keep run-history accumulators scoped to each run.
- Prefer private short-lived OS temp files deleted in both normal and exception paths; disclose identifier-at-rest and crash-remnant risks. This is not authorization for automatic archival pruning, a durable checkpoint or an authenticated trust anchor. Those mechanisms require separate design and crash/restart tests.

### compare cost before designing durable checkpoint
- Prefer a no-mutation, opt-in **real-run**, one-report measurement tool before changing production memory policies. Reuse accepted disk-backed and in-memory quality report implementations; isolate each in a fresh subprocess to reduce cross-mode heap contamination. Canonical SHA256 of the complete output is a hard correctness gate across all repetitions, not a proof of immutable log identity.
- Report wall time, traced Python peak, nullable platform RSS and final SQLite main DB size with explicit measurement caveats. Never publish raw event/document identities or source/temp paths, and do not misrepresent traced allocation, SQLite file size or Linux CI as a Windows production memory/ES acceptance guarantee. Durable checkpoint/rotation/delete remain separate, explicitly authorized future work.

### benchmark physical-input stability before output
- Keep the previous full-report SHA256 parity gate and add cheap read-only bounded filesystem stat generations of exactly the quality components already used by the offline report (active, canonical shards, optional manifest). Check at baseline, before, and after every child process; reject any change without writing or printing input paths.
- Prefer fail-closed measurement over presenting unverified speedups; still require stopped producers and honest metadata-only limitations rather than broadening to online locking, automatic retention, persistent checkpoint or user-content serialization.

### benchmark native Windows memory metric without dependency
- Prefer Windows `GetProcessMemoryInfo(PeakWorkingSetSize)` via stdlib ctypes/PSAPI to avoid adding psutil/native vendor dependency or copying sensitive process paths into diagnostics. Preserve existing nullable `peak_process_rss_bytes` and per-child isolation; API failure returns null, not zero or fabricated traced-RAM-equivalent value. Linux/macOS retain `resource.ru_maxrss`.
- Label the resulting number precisely as historical Windows working-set peak, not private commit or memory boundedness proof. Simulated Linux CI cannot substitute actual Windows process acceptance. PR #231 and retention/rotation remain independent.

### separate report compute and isolated child-process timing
- Preserve prior `median_seconds` as exact child-measured report function runtime and add a distinct parent-observed `median_subprocess_wall_seconds` in the experimental opt-in benchmark summary. A parent monotonic timer around `subprocess.run()` is the simplest trustworthy measurement of child startup/import/IPC/termination cost; do not trust a worker-supplied wall-time field. Keep the old metric for compatibility and no child worker JSON shape change.
- Clearly distinguish single-child wall duration from entire CLI orchestration and production throughput; do not claim genuine speedup without real stopped-run samples. Retain source integrity checks, privacy sanitization and SQLite cleanup.

### fail closed on non-finite benchmark numbers
- Python `json.loads` accepts NaN/Infinity extensions and can parse exponent overflow to non-finite floats despite expected JSON. Use strict `parse_constant` rejection plus `math.isfinite` on numeric worker duration; enforce native `tracemalloc` peak bytes as integral; reject a failed/non-finite parent monotonic sample. Do not publish statistics based on non-standard JSON numbers, convert missing values to zero or print child error payloads.
- Preserve the opt-in summary schema and report-v1 behavior; serialize final output with `allow_nan=False` as defense in depth and give fixed path-free CLI errors. Source-generation and full report digest gates remain required.
## Current ES data integrity and acknowledgement decisions

- Keep `article_date_iso` and `article_date_precision` as a single consistent publication-date evidence pair from one source slice, validated strictly for null/unknown and day/month/year alignment. Never assemble a plausible-looking date/precision from separate malformed slices or infer the article date from `Event_Timeline`/`time_raw`. This protects indexing semantics from plausible but false publication dates.
- Preserve Event[] `event_id` uniqueness and linked `event_ids` referential integrity at the strict output profile; no schema-invalid result should be promoted to ES writeback.
- For buffered ES bulk writes, a successful queue/dispatch is not Row Merger success. Require sink `confirm_writeback()` acknowledgement before releasing source and Success artifacts; on error retain replay evidence and discard only unacknowledged queued actions. Do not confuse acknowledgement with search refresh/readback visibility. Operator must separately prove stored ES results before production bulk replay.

## Current single-extract resume data-integrity decision

- For one extract-stage `merge_slices: true` JSON stage writeback (Issue #211 / PR #213), **original complete raw source membership is the authority**, not the surviving TODO filenames after successes. Keep the hash-only manifest `_extract_slice_identity/source/original.json` independent of destructible stage snapshots; verify source SHA, ordered raw chunk hashes, saved filename map, effective stage-task hash and original dispatched prompt hashes across `resume` and `smart_reset`.
- Accept reused Success and committed split child attempts only after verifying their original dispatch/child lineage; refuse incomplete/changed sources or stale stage tasks rather than silently dropping completed siblings or re-rendering a retry child as a new source. Regenerated source text in `_stage_outputs/original` is **transient**, never replacement authority.

## Current cache-aware throughput attribution decisions

- Preserve `processing_tps` as historical source metadata; compute the GUI-only `total_tok_per_s` and `effective_tok_per_s_est` distributions only for authoritative API-usage slice calls with nonzero elapsed. Do not reinterpret a failed/missing measurement as a zero token count or cache hit.
- Provider `cached_input_tokens` and `cached_input_token_source=provider_usage` are authoritative only when explicitly available (valid zero is distinguishable from absent). A possible cache reuse **heuristic** must be labeled and separately counted, derived from **two or more previous stable template sizes** within the **same model/endpoint/task/stage/source**, bounded to a 50% template discount; never compare across stages, write estimates into audit provider cache columns, or describe heuristic throughput as hardware-only generation speed.

## Archived History

- `.codex/archive/decisions.md-20261027-213700.md` — **exact pre-compaction** snapshot (Git blob `2fcdc099dfd3065af18402dfc8e7aed9618b9195`) preserving dated decisions, prior review statuses, PR SHA/CI evidence and older archival references; consult only when tracing history.
- Earlier archives referenced inside this snapshot remain unchanged; no history was deleted.
- Active summary reconciled with GitHub `main` `46b7c7290417421a6dc09e114f82c1066ce0179d` after user-authorized PR #239 merge and Linux postmerge `offline-e2e` success; Windows runner jobs remain queued/operator-deferred.

## 2026-10-28 offline quality output/control-plane separation

- A read-only summary should never share its destination namespace with a quality archive consistency manifest, even though both filenames end in `.json`. Reject the canonical ledger filename pattern unconditionally (including uncreated/other-run manifest targets) before scanning sources or creating temporary SQLite; also reject symlink report output aliases. Keep the original generic atomic JSON writer unchanged to avoid affecting unrelated sinks.
- This rule prevents inadvertent overwrite by CLI users; it is not an online-writer lock, an authenticated manifest trust root or a durable checkpoint. Preserve normal `--output quality_summary.json` behavior and all report-v1 metrics.

## 2026-10-28 LLM-call failure report output namespace decision

- Keep the existing `llm_failure_report` report-v1 shape and strict CSV audit reader. Reserve the `processing_quality_events_*.jsonl.manifest.json` SHA256 ledger filename **regardless of destination directory**, before CSV replay. Retain separate within-source-directory `llm_call_audit_*`/quality artifact prefix rules, casefold for Windows and reject symlink output aliases. Do not broaden generic `atomic_write_json` behavior or interpret this as a race-free file sandbox.

## 2026-10-28 LLM call failure time interval decisions (pending PR acceptance)

- Use producer-emitted local-second `timestamp` only for optional `llm_failure_report --since` (inclusive) and `--before` (exclusive), validating strict canonical `YYYY-MM-DDTHH:MM:SS` and `since < before` if both are supplied. Reject offset/Z/ambiguous timestamps; do **not** fabricate UTC, retry UUID or document identities. All records in a filtered snapshot must have valid timestamps, including out-of-window rows; otherwise fail closed rather than misrepresent denominators.
- Preserve unfiltered report v1 and legacy parser/snapshot budgets. Filtered v1 adds fixed `time_window` with producer-local clock labeling, and per-run excluded count. History keeps independent run snapshots; no cross-run denominator pooling or online mutable-writer guarantee. No runtime CSV producer or LLM path changed.

## 2026-10-28 audit identity boundary (pending review)

- Mint a private-data-independent UUID4 per recorded `log_llm_call` entry and append it to **new** CSV/XLSX audit exports as `audit_record_id`; no hash of prompt, document, endpoint, error or raw provider payload. Do not reuse an audit-row UUID as a provider request ID or retry-family identity; a crashed/unlogged request has no row. For a running legacy CSV with precisely the former header, emit the former column width. Reject other existing headers instead of silently misaligning output. Preserve unfiltered/filtered `llm_failure_report` v1 denominators and privacy; do not infer retry rates from UUID counts.

## 2026-10-28 explicit Worker invocation ID decision (pending review)

- Use `uuid.uuid4().hex` generated by `PromptAPIPipeline.proc` immediately before the real `CallLLMAPI` invocation, forward it to optional validated `log_llm_call(worker_call_id=...)` and store as a trailing CSV/XLSX column. Direct audit invocations without that boundary leave it empty (no guessing from prompts, URLs, timestamps or error text). Preserve both #245 and pre-#245 headers by exact width on append; incompatible headers fail closed. Never interpret this as SDK HTTP attempt identity, retry group, unique document identity, successful provider processing, sink acknowledgment or a new failure-rate denominator. Keep v1 failure summary unchanged.

## 2026-10-28 Worker wrapper-return attribution decision (pending review)

- Separate explicit `CallLLMAPI` normal-return evidence (YES/NO/unknown) from local postprocessed `ok`; capture the observation at the actual Worker call site, never infer from a nonnull `response` or exception/error text and never label it provider HTTP acknowledgement. A non-null flag requires a valid Worker-call UUID; otherwise direct audit callers emit an empty/unknown field. New CSV/XLSX final field preserves current and three earlier exact headers without modifying source bytes/widths. Do not extend report-v1 denominators or count logical retry families from the return flag; source-authoritative retry dispatch remains separate.

## 2026-10-29 explicit persisted split lineage ID (pending review)

- Extend the already-durable v1 SHA256 parent+two-child JSON repair *intent* journal with an independently random UUID4 `split_family_id`; don't hash user input to create group identity or infer from filenames alone. Require direct parent journal with matched child SHA256 and canonical two-child name pair before inheriting ID for child or nested split. Preserve original hashes, file format version, resume/rollback code and old journals (unknown ID), and never claim journal identity means actual committed children or LLM calls. Keep Worker audit CSV/XLSX/report v1 untouched; separate actual Worker-to-family correlation and cross-run/request retry grouping later after source-level proofs. No Merge without explicit user authorization.

## 2026-10-29 source-verified Worker/split correlation

- The first parent split journal is written after its LLM response is repaired; hence look up lineage **after** postprocessing while preserving a bounded-memory verified actual queued-source observation from **before** `CallLLMAPI`. No reliance on filename/time/error strings, no prompt payload in the new UUID field, no changes to failure-report v1 or queue/SDK retry strategy. Attach only with Worker call ID and wrapper-return observation; four preceding audit headers remain byte-width compatible. No claim of authenticated source generation or HTTP retries; #231 is independent.

## 2026-10-29 #231 main-first safety reconciliation (pending acceptance)

- Avoid a blind merge of the 224-behind branch: preserve `main`'s stronger #249 source verification, GUI budget guards and immutable Codex archives. Make #231's recovery functionality a two-parent integration commit (old #231 head + accepted current main as parents) with a tree built from current main plus only its new recovery module/CLI/tests and bounded docs. Explicit stopped-producer rollback uses exclusive hardlink, never unlink sealed shards, never rebaseline SHA256 ledger; run latest-head full Linux E2E/archive regression and formal Codex review. Never merge without explicit user approval.

## 2026-10-29 first queue evidence phase (pending review)

- Record only actual completed TODO/RUNNING rename observations, not guessed retry ancestry from matching filenames, hashes, exception text or existing Worker IDs. Store event UUID4 and bounded source bytes digest in item-local append-only JSON; never log raw prompt, basename, path or response. Observation failures must never abort or requeue an already claimed task. A later phase will require a durable verified source generation/lease to correlate retry attempts and Worker calls. No changes to report-v1 denominators.

## 2026-10-29 phase 2a: trusted queue claim → Worker evidence only

- Pass the **exact random UUIDv4** emitted on the real successful queue claim directly from dispatcher to its Worker instance; never retrieve possible receipts by path/hash/time searches. Preserve the historic two-tuple queue API via a write-only optional `claim_ids_out` map and keep queue progress independent of telemetry publication. Before real `CallLLMAPI`, require the existing actual source/prompt check plus a bounded exact receipt re-read with file SHA256 and strict schema. Record an optional final `queue_claim_event_id` alongside `worker_call_id` in new CSV/XLSX, preserving five prior widths; existing report-v1 denominators unchanged. General Retry Family inference is explicitly deferred until authoritative generation-linked requeue and dispatch evidence exists, and never collapsed with the JSON `split_family_id`.

## 2026-10-29 phase 2b: preserve source bytes over automatic nested dispatch (pending)

- Keep public queue tuple shape and Worker event handoff unchanged. Fail closed for ambiguous pending basenames, rather than auto-renaming or relabeling task files (which could invalidate downstream source/Success/split journal identity). Require hardlink-capable same-filesystem exclusive destination creation, inode verification and successful source unlink before treating a TODO as dispatched. Reject symlink/hardlink aliases; do not fall back to replace-on-existing, do not silently delete conflicts. No claim of cross-restart crash-atomic rename; recovery/Success collision and true logical Retry Family remain separately scoped.

- **Producer done ≠ teardown:** when no-clobber TODO claim is permanently blocked, avoid circular wait for `pending==0` by separate ctx-shared producer-complete and blocked-queue events. The real consumer owns blocked detection only once no running jobs remain, and the orchestrator owns final terminal failure and teardown. Preserve sources and truthful failed status; never reinterpret an empty dispatch batch as a successful drained queue.

- On terminal blocked queue, do not remove registry entries just to satisfy merge exit and do not wait indefinitely for impossible `_all_slices_done`; bound Row Merger to one final normal scan after explicit blocked event and teardown stop_event, then close sink and preserve remaining artifacts. Coordinator owns authoritative terminal failed status. Normal job shutdown remains unchanged.

## 2026-10-30 — preflight anonymous Elasticsearch design decision

- Keep `verify_private_connection_profiles.py` strict by default; a single empty `es_user` or `es_pass` remains an error, and full-directory checks cannot silently accept anonymous endpoints.
- Permit **only explicit one-file `.py` ES development/test** override `--kind es --profile FILENAME.py --allow-anonymous-es` when both fields are literal blanks and `CZJLLM_ENV` is unset/known nonproduction; production, staging and unknown environment names refuse the override. SQL and YAML never receive it. Other security and connection-shape checks are unchanged.
- This is static validation policy, not a change to actual ES runtime authentication, a production credential bypass, or a claim of real endpoint login. Operator must verify that ES PROFILE_4 intentionally supports anonymous access, otherwise configure private credentials.

- **Anonymous preflight parity refinement (Codex P2):** ES `validate_es_config` normalizes username via `.strip()` but checks password raw truthiness. Static anonymous exception must follow that asymmetry rather than treating whitespace-only passwords as empty; do not alter runtime authentication semantics for a preflight-only fix. Require literal empty/None password and reject dynamic expressions to avoid claiming unverifiable anonymous behavior.
