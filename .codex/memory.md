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
