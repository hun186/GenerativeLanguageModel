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

## Active Work — 2026-10-19 PR #216

- Branch `fix/es-article-date-and-importance-shape-20261019` is an UNMERGED proposal. A user's fresh 37,286-row ES production log showed two distinct strict schema errors after the earlier operational retry mitigation:
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
