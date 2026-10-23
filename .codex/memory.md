# Project Memory

## Current Summary

- GenerativeLanguageModel supports TXT/Table/SQLite/SQL Server/Elasticsearch, local LLM (Ollama), sliced prompt processing, multistage extraction, reduction, and guarded database writeback.
- Reduction Engine v1 A–L is complete/release ready. Reduction v1.1 work and GUI token/context dashboards were completed in previous merged PRs. Historical exact commit/CI evidence is preserved in the archive cited below.
- Production cancellation remains cooperative, stops new scheduling while in-flight workers/writeback drain. Runtime status, metadata, tracking and audit history must not be falsely reported as all-completed.
- PR #213 was merged at `8dd4f41b23c1df2c6a5cad8d13aeee4a23174649`: single-extract SQLite/Excel E2E and durable original source/dispatch provenance checks. Historical review/corrective record in archive.
- PR #214 was merged at `15d14cba8c0382a766b25be89e91cfeb3c16339a`: strict ES multidim_event_json collision-free chunk-local Event ID merge and corresponding local event_ids remapping; correct profile-specific generic-vs-strict merged outputs; source-specific stage/combined writeback; Impact extra array nesting normalized. Live production showed successful ES writebacks for some rows; this does not imply all records succeed.
- PR #215 was merged at `25667c49b65ce078c1414949a637f9ba65863bc6`: malformed chunk-local E3/T1 references fail closed with concise log and one-time terminal status; raw input and Success preserved, ES record pending for future run; prevents Row Merger, fallback and deferred-source concurrent claim/race/double counting via terminal legacy-claim state. Exact-head Linux offline E2E and Codex had no major issues before user-authorized merge. Windows self-hosted jobs may remain queued.
- Live Windows Ollama + internal ES are not available to Hosted CI, so production acceptance needs 1-3 controlled row tests; never claim an offline pass establishes successful live persistence.
- Required full requirements install may be constrained by pinned GitHub peft clone proxy 403; targeted Hosted offline dependencies are authoritative when configured and validated.

## PR #216 implementation/review history (superseded by merged main)

- Branch `fix/es-article-date-and-importance-shape-20261019` was merged into main on 2026-10-19 (details in current status below). A user's fresh 37,286-row ES production log showed two distinct strict schema errors after the earlier operational retry mitigation:
  1. `non-null article_date_iso cannot use precision='unknown'` — independently merging article_date_iso and article_date_precision after a left unknown vs right day conflict created mismatched metadata. For treaty/convention excerpts, a known treaty signature date (1982-12-10) is NOT necessarily the document publication date; do not promote inferred event dates to article dates.
  2. `contains fields not present in current schema: ['coverage','credibility','impact','importance_score','novelty']` — these are the current profile's sanctioned `importance` child keys incorrectly emitted at article root, not arbitrary unknown fields.
- Change in `czjLLM/utilities/slice_merge.py`: only for strict multidim_event slice reconciliation, select article_date_iso AND article_date_precision from the same internally consistent source-slice pair; honor existing prefer_left / prefer_right precedence, including null/unknown; never derive missing dates, reject if no valid source pair through existing strict output profile. Generic JSON merging unchanged. Log audit `article_date_pair` if selected pair replaces an inconsistent independent merge.
- Change in `czjLLM/es_mode/output_profiles/multidim_event.py`: before strict top-level field rejection, structurally move only the five exact known score keys to nested importance, preserving values; if existing nested score conflicts with flat score, reject rather than choose; existing type validation rejects noninteger/bool and unknown-field rejection remains.
- Added focused regression tests in `tests/es_mode/test_multidim_event_slice_merge.py` and `tests/es_mode/test_multidim_event_field_types.py`; Linux `.github/workflows/ci.yml` now runs both plus row-merger-schema regression. New Hosted exact-head CI and fresh Codex review REQUIRED. No merge without explicit user authorization.
- The production watchdog's repeated `[watch]` / ETA progress lines are status updates, not necessarily failures; four in-flight workers and scheduling continue in the example. Remain cautious interpreting approximate ETA and percentage. Schema errors are terminal/pending for the current run, not evidence the entire batch stopped or wrote all rows.

## Important Safety, Contracts, and Follow-up

- No guessed Event IDs, semantic event relations, fabricated article publication dates, or invented scores. Leave malformed unknown or conflicting data pending when structural correction is ambiguous; retain original and `Success` artifacts and trustworthy audit.
- Test source date-pair consistency and exact ES profile, and validate production sink normalization with a small local acceptance run after merging only if authorized.
- Other outstanding technical/product areas (Reduction/GUI, Issue #211, previous code review rounds, audit benchmarks, SRAF-independent work) remain recorded in archived project memory and the live `.codex/backlog.md`.

## Archived History

- `.codex/archive/memory.md-20261019-before-pr216.md`: immutable full previous memory snapshot (70,905 characters) through PR #215 review, including all prior commit IDs, exact CI results, corrected and pending statuses as they were known at their respective times. Do not interpret obsolete "pending" statements in the archive as current Hosted PR status.
- Existing prior compaction archive references are preserved in that snapshot and under `.codex/archive/`.
- 2026-10-19 compaction performed because active memory exceeded 40 KB; no previous history was discarded, only moved to archive.

### PR #216 first Codex review corrections (2026-10-19)

- First formal Codex review of early head 6c69a8bcff found P1 #4312588912: if all source date/precision pairs were invalid, independent generic scalar merging could accidentally synthesize a valid pair from parts of distinct malformed slices. It also found P2 #4312588916: date with legal surrounding whitespace was rejected as a candidate even though strict output profile trims it.
- Fix 850e548 updates the strict-only pair selector to return a whole unmodified INVALID pair from one original slice when none is valid, so ES explicitly rejects it, or removes both assembled fields if no source had a complete pair. Valid ISO dates are trimmed exactly as the output profile permits. Conservative null/unknown remains valid and precedence unchanged; no event-derived publication date.
- Regression e216734 covers invalid cross-composed pairs, incomplete-only pairs, and legal whitespace in complete valid pairs, including no mutation of cached slices. Latest exact-HEAD Hosted CI and fresh Codex review required; do not claim pass or merge without explicit authorization.

### PR #216 second Codex review corrective (2026-10-19)

- Review of interim head d325dcf7b4 found P2 #4312618204: nested importance.coverage=True with flat coverage=1 (or 85.0 vs 85) can pass equality and be silently overwritten, hiding invalid original nested type before validation.
- Fix a1eaf744 ensures both flat and existing nested score representations individually satisfy integer-or-null (not bool, float, string, list) BEFORE any equality/conflict check or relocation. Structural relocation remains lossless and conflicting legitimate integer values are still rejected.
- Regression 66ec0a2 tests True vs 1, False vs 0, float vs int, string vs int and valid int vs bad bool.
- Exact-head Hosted CI and Codex review must be rerun on the new head. Review threads will be resolved only after responding with fix evidence. Not merged.

### PR #216 third Codex review corrective (2026-10-19)

- Review of interim head a08f334b41 discovered P2 #4312663810: when no slice contained BOTH article_date fields, strict merger removed cross-assembled/incomplete metadata, but did not set report.changed or include an audit sample. In single-slice invalid cases the merge therefore mutated the result silently and audit logger could suppress the correction.
- Fix 73075f1 records an explicit article_date_pair_incomplete audit sample with the removed fields and sets changed=true whenever those fields were present; no fabricated date, strict ES still rejects missing required pair. Test 94369af checks real strict merge of a single incomplete article and asserts changed/audit/strict rejection without modifying original Success content.
- Fresh exact HEAD CI + Codex review required; no merge or real ES acceptance yet.

### PR #216 fourth Codex P2: malformed source score erased before ES profile (2026-10-19)

- Codex P2 #4312692107 on HEAD a328985 noted that post-merge strict ES validation was too late for malformed input scores: source 1 coverage=85 and source 2 coverage=True / 85.0 could collapse to coverage=85 via generic prefer-left merge, hiding a source error. Prior nested-vs-flat correction did not address multiple flat source values.
- Fix 2f640ee introduces terminal MultidimEventSchemaError and validates exact five flat/nested importance score fields in EACH original source before deep merge when multidim_event=True; Event-reference error subclasses new typed error. Combiner and Row Merger/fallback share PR #215 terminal cleanup, preserving Success/input and ES pending rather than flooding logs. SQL/generic merge remains unchanged.
- Regression ad9f8a1 verifies later invalid flat/nested values and container types cannot disappear under merge, generic merge stays generic. Regression 7b9bfa9 tests one-shot Row Merger status for both E3 reference and invalid score; production-like JSON combine regression proves concise COMBINE-SCHEMA and preservation.
- Proactive refinement e95604f validates per-slice contradictory flat vs nested values before different slices can make the final merged representation accidentally agree. Regression aa3a0f7 checks this exact source conflict.
- Latest exact-head Hosted CI and fresh Codex review required. PR is open and must NOT be merged without explicit user authorization. No live ES acceptance claimed.


## Current Hosted Status — 2026-10-19 (supersedes PR #216 pending notes above)

- Hosted `main` is `8dfbdabdee3e15654a29e4020b0b1aa704b04362`, PR #216 merged 2026-10-19 (accepted head `5eb44a5cf93b8b71c875129f26b9c43c7ab7598d`). All five PR #216 review threads resolved. Linux offline-e2e succeeded at exact accepted head; Windows 3.10/3.11 self-hosted jobs remained queued at verification. Post-merge main Push CI `39243409973` has a successful offline-e2e job, while Windows remains queued, so the overall workflow is not green.
- New follow-up branch `fix/es-writeback-ack-before-row-cleanup-20261019` targets a separately identified safety issue: `ESSink.write_main()` can buffer updates below flush thresholds, while Row Merger currently marks the document complete, archives its source and prunes Success BEFORE ES bulk has acknowledged the buffered update. Subsequent flush failure can leave completion accounting ahead of actual ES state. This is a code-level risk, not proof it occurred in production.
- Proposed fix: `ESSink.confirm_writeback()` drains the ES pending bulk; Row Merger invokes this capability after all row writes and before status release/source backup/Success cleanup. Explicit success is an ES bulk acknowledgment, not an immediate search refresh. Non-ES sinks keep their existing behavior. Error propagates to existing schema/transport failure policy; source and Success stay available for retry or pending.
- Regression tests cover delayed acknowledgment (including one transport failure), terminal ES mapping rejection without accidental cleanup, and explicit buffered ESSink flush. Hosted exact-head CI and Codex review required for this NEW PR; it remains unmerged until explicit authorization. Do not claim live Windows/ES/Ollama acceptance.
- Next: verify 1–3 real ES documents including previously problematic IDs, check source provenance and exact deployed executable revision, ES stored payload, pending/completion state and audits, and only then consider resuming a 37,286-item batch.

### PR #217 first Codex review follow-up (2026-10-19)
- First exact-head review `98ae6aeb6ab5aea0fb4e18615ef71b1dafaac8fb` found P1 #4313694330 and P2 #4313694341/#4313694349. A failed row A's retained bulk actions can be accidentally flushed/attributed to later row B; repeated 429 errors duplicate actions; some deterministic HTTP 400 variants were classified retryable.
- Corrective: once any ES write or confirmation fails, discard that Row Merger sink's unacknowledged buffer so the preserved source and Success can be replayed cleanly. The serial per-row acknowledgment invariant means the buffer has only the current row's actions at that boundary. Also handles errors raised inside write_main's threshold flush. All HTTP 400 bulk responses are terminal (including mixed 400/429 actions for a single row); 429/5xx remain retryable.
- Added targeted regression for A/B isolation, pre-confirm flush exceptions, 400 variants, and 429 replay. Pending new exact-head Hosted CI + fresh Codex review + thread resolution. No merge or live ES success claimed.

### PR #217 second Codex P1 (2026-10-19)
- On exact head `58c69006855f811a27dbc4b335d1cd2ad55700d9`, Codex P1 #4313781359 found that `_process_flatten_target()` swallowed ESSink.write_flatten() threshold-triggered HTTP 400 failures. The bulk buffer could be cleared by the terminal failure while subsequent confirm_writeback() returned success, incorrectly finalizing the row.
- Proposed corrective: for sinks offering the explicit ES `confirm_writeback` handshake, propagate flatten write exceptions into Row Merger's normal schema/transport error path before finalization; other sink types keep best-effort legacy flatten semantics. Regression checks both ES and non-ES behavior and context restoration. Fresh exact-head CI + Codex review required before resolve/merge.


### 2026-10-20 Processing Quality monitor PR #218 (unmerged)
- PR #217 was merged into main as `a7f441136c63caee15214610ee83abc7a5049e38`; exact-run Windows/real ES acceptance still open. Older "PR #217 pending" entries are historical.
- New branch `feat/processing-quality-observability-p1-20261020` / PR #218 adds run-scoped `processing_quality_events_<run_id>.jsonl`, per-slice JSON validation/repair and distinct document schema/confirmed-writeback events; increments Tk GUI quality widgets in a separate collapsed panel.
- Quality rates have independent denominators (slice JSON validation attempt, completed repair attempt, distinct document writeback decisions) and unknown values for zero samples. A repaired JSON is not a failed document. Raw prompts/outputs are excluded.
- Linux offline-e2e (including tests/test_processing_quality.py), Codex exact-head review, Windows runner and real ES acceptance are validation gates; treat current implementation as unmerged and unaccepted until their actual evidence is recorded.

### 2026-10-20 PR #218 merged + offline report follow-up (separate branch)
- PR #218 merged at `bfe49413071a80a67d1a0d8208ef3706d5411b7f`. Code-reviewed exact head `b3d8a7...`, Linux offline-e2e success; real Windows/LLM/ES acceptance is **not** complete and intentionally deferred until model capacity is available.
- Next development is isolated from pinned acceptance main: read-only per-run/history JSON report CLI built on QualityTailReader/QualityAccumulator and atomic_io, no new quality log, no LLM/network/DB. Includes explicit low-sample/unknown-denominator and concurrent-tail warnings. Unit/Hosted CI and Codex acceptance pending; do not merge automatically.

- First PR #219 Codex exact-head review found P2: complete malformed JSONL rows were silently skipped, making offline report look complete. Fix now tracks `QualityTailReader.skipped_corrupt_lines` across polling/reset, surfaces degraded report status + count, with focused regression. Fresh Hosted CI/Codex review remain required.

- Latest PR #219 Codex found P2 for unsupported complete event records and same-file rewritten contents when current size >= prior read offset; corrected QualityTailReader to distinguish duplicates from invalid schema and to reset generation on inode or bounded committed head/tail change. Added offline tests for both. Hosted CI failed in prior heads with job-log API 404 BlobNotFound; cause not proven; must re-run/inspect exact head before marking accepted.

- Additional defensive hardening before latest re-review: validate quality event/code pairs and optional scope, and reject document events lacking document IDs; synthetic legacy fixtures without a scope stay accepted. Targeted tests added. No LLM or live sink functionality was changed; Hosted CI status remains a separate, runner-allocation issue until proven otherwise.

- Latest PR #219 Codex also found conflicting duplicate event IDs and GUI reset-to-empty suppression. Accepted-event IDs now hold a compact canonical JSON SHA-256 signature and only identical replays bypass corrupt-line accounting; a file generation reset is `changed=True` so the Tk poller clears old stats. Tests added; exact-head Hosted CI and Codex re-review still outstanding.

- New Codex P2 on 5abe4cd: NaN/Infinity parsed as JSON and blank event_id accepted. Added strict parse_constant decoder, nonblank IDs, canonical signature finite-float requirement and regression. Fresh Codex/CI exact-head evidence still required; Hosted Linux runners have repeatedly not been provisioned (runner_id=0, steps=[]); do not claim tests passed. PR remains unmerged.

- 2026-10-21 PR #219 Codex P2 on `e6dd2bd...`: an explicitly provided null scope was accepted like an absent legacy scope. Fix now validates scope on field *presence* (reject explicit null/blank/mismatch) while still accepting truly absent legacy fixtures. Added reader/report + accumulator regression; exact-head Hosted acceptance and Codex review pending, no merge.

- 2026-10-21 PR #219 new Codex P2: excessively deep valid-looking JSONL line raised uncaught RecursionError and prevented later events from being reported. Reader now catches decoder RecursionError and categorizes complete line as degraded, and duplicate/signature serializer also handles recursion failures. Offline regression verifies deep invalid line followed by a good event continues safely. User-approved GUI terminology now says 'LLM 文件結構異常（待處理）' and chart caption '文件結構驗證未通過 / 已判定文件'. Fresh exact-head Hosted CI and Codex review requested; no merge.

### 2026-10-22 post-PR #219 next Reduction v1.1 work (open PR pending)
- PR #219 merged at `7d341aaf63470d4fa4b9e4253b71dd68d62e18c8`. Latest head `e3a2f68` Codex completed with zero findings; Linux PR offline-e2e passed after repo became public; post-merge main push `39710465574` also passed Linux offline-e2e. Windows self-hosted 3.10/3.11 jobs remained queued, and live LLM/ES acceptance remains unverified.
- New branch `feat/reduction-v1-1-legacy-artifact-inventory-20261022` is a read-only legacy checkpoint/runtime inventory, reusing the L3 approved bounded traversal. Results contain counts only (unmarked, manifest-looking, nonregular marker, recognized runtime, incomplete scan), not artifact paths/IDs; no contents read or marker/adoption/deletion performed. Unmarked regular run.json is explicitly NOT validated or migration eligible.
- New CLI and focused tests, usage document and Hosted CI step are proposed. Exact-head Hosted tests and Codex review are acceptance gates; no merge without explicit user instruction. #203 Semantic Cache stays deferred.

### 2026-10-22 PR #220 merge and next quality follow-up

- PR #220 merged to main at `d42da809ced603544e95ff6fbccdc82cda47033a`. Exact PR head `ef244c3a...` passed Codex with zero findings/0 unresolved threads; Linux offline E2E and legacy inventory/L3 regressions succeeded. Main push run `39735525575` Linux offline-e2e also succeeded; Windows selfhosted jobs remain queued. Legacy tool is inventory only, no migration or GC ownership adoption.
- New branch `feat/processing-quality-llm-failure-audit-p2-20261022` adds independent **read-only** LLM call-failure CSV summarization. Fixed-label allowlist taxonomy from existing `ok=NO` rows only; unknown and corrupt outcome observations remain explicitly unknown. Never exports raw exception/prompt/model URLs/file paths/doc IDs, never modifies historical CSV/XLSX. This is request-level audit coverage, not document, Worker/Stage, or ES durability. No live model, SQL/ES, or GUI changes.
- Hosted exact-head offline focused tests and Codex Review required before merge; no automatic merge. Real Windows/LLM/ES acceptance remains deferred and must not be claimed.


### 2026-10-23 Hosted handoff and Consumer-quality PR (pending)

- Hosted main `85625666221655da507d3938251821e04b295495` contains merged #221. Main push run `39810479815` Linux offline-e2e succeeded (job `119935062535`), while Windows self-hosted 3.10/3.11 jobs remain queued: entire workflow has not concluded.
- Issue #211 was closed after #212/#213 merged, #213 exact-head Linux offline-e2e job `116860266565` succeeded and all 28 review threads resolved. No Windows/provider/real SQL/ES persistence acceptance is claimed.
- Consumer-quality branch adds run-scoped, payload-free incidents for legacy batch timeout, caught round exceptions and uncaught consumer termination; counts are events, not failed slices/documents. Stage-managed workers remain outside this scope. Focused tests added; exact-head CI and Codex review still needed, and no merge without user authorization.


### 2026-10-23 PR #222 first formal Codex P2 corrective (new exact-head validation pending)

- On original PR head `099d32ca6827f465a3cdce0bfee3e43473a3e719`, Codex formal review completed and found P2 #4357453454: public run-scoped quality event emitter allowed supplied `document_id` or `slice_id`, persisting those identifiers despite the payload-minimal contract. One unresolved review thread remained.
- Corrective commits add explicit event-specific empty-identity validation at `emit_quality_event` **before writing any output**, and mirror the validation in `QualityAccumulator.add` so old/malformed JSONL lines degrade and do not enter any numerator/denominator. Targeted tests check rejected identity-bearing emit attempts and malformed complete-line reader behavior while preserving valid run-event counts.
- Prior exact head `099d32c` Linux offline-e2e SUCCESS (run `39922388801`, job `120310471484`); its success does **not** validate these new corrections. Fresh exact-head Hosted CI + formal Codex re-review and resolution remain required; Windows self-hosted 3.10/3.11 queued, no live Ollama/ES acceptance.

### 2026-10-23 merge #222 and next bounded Row Merger quality work

- Formal Codex exact-head clean on `e16c58341b0f908955d5c74d18f193e153a45239`; original P2 identity-leak review thread resolved. User authorized merge; PR #222 merged as `bd3fc22c647ef296c2210750a69c78c168c50904`. Post-merge main offline-e2e job `120397446551` (run `39948655415`) SUCCESS; Windows self-hosted 3.10/3.11 remained queued and the user directed they be skipped until a runner is available.
- Next independent branch `feat/quality-row-merger-retry-incidents-20261023` adds run-only, no-identity Row Merger non-schema retry observations `ROW_MERGER_PREPARE_RETRY` / `ROW_MERGER_WRITEBACK_RETRY`, rate-limited to the existing watchdog warning cadence. Separate incident count and allowlisted codes go to Processing Quality accumulator and GUI/offline report, without changing document-denominator math, sink acknowledgement, pending/retry or cancellation semantics. Tests cover privacy and one failed buffered-ES write followed by successful retry.
- **Status:** Implementation committed to new branch, exact-head Hosted Linux CI and new formal Codex review not yet accepted; no merge without user authorization. Producer/Stage Worker, retention and Windows/real ES/Ollama testing remain separate.

### 2026-10-23 PR #223 first Codex P2 and Hosted CI correction

- Formal Codex review of initial PR head `7eabcb500808b59a553ea66d0c0bd60ae89da39b` completed with P2: `_resolve_combined_path()` swallows a non-schema `combine_api_finished_item()` failure before it reaches the new writeback retry incident emitter; a genuine preparation retry was invisible. A shared watchdog-local, throttled, best-effort run-event helper now covers both the earlier combine exception boundary and the outer writeback handler while preserving existing retry/terminal/cancellation behavior.
- Initial Hosted Linux offline-e2e run `39954419192` failed the focused Row Merger test because it expected one *total* JSONL event after ES flush failure then acknowledged successful retry. Both a run-scoped retry incident AND a document-level writeback confirmation are valid (two events, distinct scopes). Corrected assertions segregate incident from confirmation; added direct combine-fails-once-then-succeeds production-path regression with payload-free event.
- New exact-head Linux CI and fresh formal Codex review required. Neither initial failed CI nor old Codex review validates these correction commits. Windows self-hosted Runner remains operator-deferred; no merge without authorization.

### 2026-10-23 PR #223 merged; Producer operational incidents P2 follow-up (branch awaiting acceptance)

- PR #223 Row Merger run-scoped retry incidents was user-authorized merged into `main` as `a9240f826bfef9a999848017a254c69c5c05f748` after exact-head Codex review `6b600337c9d887a1fec1a04e0a28d251546be1de` reported no findings and Linux offline E2E job `120443400448` passed; its initial combine-preparation P2 was fixed. Post-merge main CI #39974457753 Linux offline E2E separately pending at follow-up start; Windows self-hosted queued and user defers Windows acceptance.
- New P2 branch `feat/quality-producer-operational-incidents-20261023` instrumented Producer's caught schedule exception, caught backpressure exception, and failed multistage Future result only, with fixed allowlist codes `PRODUCER_SCHEDULE_EXCEPTION`, `PRODUCER_BACKPRESSURE_EXCEPTION`, `PRODUCER_FUTURE_EXCEPTION`. Uses existing per-run quality JSONL, read-only accumulator, GUI count. Scope run; neither document IDs, slice IDs, raw exception strings, task text nor URLs are persisted. Cancellation and ordinary pending skip / zero scheduled items are not failures. Event numbers are catch-site observations, not distinct failed documents, executed LLM calls or full pipeline reliability.
- Production retry, pending, state-release and exception handling were not changed. Telemetry is best-effort even if logging fails. Tests added for emission, reader privacy, callback exception, backpressure, future, cancel, audit write failure; hosted Linux CI now includes the focused isolated Producer test file. **Status: proposed unmerged work; Hosted exact-head CI and formal Codex review required; no claim of local/Windows/real model acceptance.**
