# GenerativeLanguageModel — Active Project Memory

## Current Summary

- **Authoritative accepted Hosted main:** `e010a5e07c45016f8f0ab4094c30bcd33825d3b5` (user-approved PR #242 merge, 2026-10-28). PR #242 formal exact-head Codex Review completed with zero Findings/Threads and Hosted Linux `offline-e2e` #40622149444 SUCCESS. Postmerge main Linux `offline-e2e` #40623677955 **SUCCESS**, including immutable archive test, verified on Hosted GitHub. Windows 3.10/3.11 are queued/operator-deferred, so real Windows GUI/PSAPI/LLM/SQL/ES is not accepted.
- Repository `hun186/GenerativeLanguageModel` supports tabular SQL/SQLite/ES and LLM multi-stage processing, merged/writeback outputs, Reduction Engine v1 and privacy-minimal per-run observability. Effective contracts live in active `.codex/{architecture,api_contract,decisions,known_issues}.md`, runtime implementation and tests; old chronology is in immutable archives.
- **Independent #231** remains OPEN/unmerged, head `a8711e9337b62e4b9c6ad62f37ba3e78ba4e8fea`; no unapproved edit/rebase/merge. Manual JSONL rotation's interrupted rollback requires separate work and operator proof.
- **Current independent reconciliation:** `docs/codex-current-handoff-reconciliation-20261028` archives the previous entire active `project.md`, `memory.md` and `backlog.md` byte-for-byte, then makes current handoffs truthful instead of repeating finished PR #240–#242 as `[ ]`. Hosted CI and formal exact-head Codex Review for this branch remain **pending**; do not Merge without user instruction.

## Accepted Recent Outcomes

- **#242** `e010a5e07c45016f8f0ab4094c30bcd33825d3b5`: failure taxonomy CLI `--output` protects other-directory `processing_quality_events_*.jsonl.manifest.json` integrity ledgers; PR Linux #40622149444 SUCCESS, exact-head Codex zero Findings/Threads.
- **#241** `fb713365b173378ba8ca82e0557e4fdd5a415650`: offline quality report `--output` protects same/other run SHA256 manifests and symlink aliases; PR Linux #40609259343, main #40616682036 SUCCESS, Codex 0 Findings, 1/1 Thread resolved.
- **#240** `21ae2cb690031c6409fd05f5cf6e4109a21548e1`: original six-file archive-first compaction, cross-platform exact blob SHA and active Linux archive gate; Codex final 0 Findings, 6/6 Threads resolved, postmerge Linux #40604470304 SUCCESS.
- **#239** `46b7c7290417421a6dc09e114f82c1066ce0179d`: finite benchmark numeric validation; postmerge `offline-e2e` #40513712390 SUCCESS. #233–#238 accepted resource/quality/GUI improvements; #212/#213 resolved Issue #211; Reduction Engine v1 A–L accepted. #203 transient cache intentionally deferred.

## Active Contracts and Limitations

- Run-scoped quality JSONL event counters are observational catch-site counts, **not unique-document or retry-denominator truth**. LLM call audit `ok=NO` is not necessarily provider failure. Provider `cached_input_tokens` may be nullable; provider/heuristic GUI `effective_tok_per_s_est` samples are distinct, grouped by stage/token source; `processing_tps` retains historical semantics.
- ES multidim `article_date_iso`/precision atomic pair, `Event[].event_id`/linked `event_ids`, strict importance five-field integer/null normalization and `confirm_writeback()` bulk acknowledgement are active boundaries; search refresh/readback is separate. Single-extract partial `resume`/`smart_reset` must prove complete original ordered slice and dispatch identity from external source manifest, not only remaining TODO.
- Sealed JSONL manifests are self-consistency SHA256, not authenticated storage; no automatic pruning, robust crash-safe checkpoint, or online rotation. Temporary SQLite spill is offline and ephemeral. Operator Windows/Ollama/ES readback plus stopped-run PSAPI and benchmark trials remain open.

## Open Handoffs

- Keep #231 isolated, avoid rewriting original source, secrets, plaintext prompts or sensitive audit paths. Engineer exact crash-safe checkpoints, bounded GUI restart/resume, logical retry denominator/attribution only with authoritative identities.
- Validate completed vs deferred states from current GitHub and operator evidence before preparing reports or starting new PRs.

## Archived History

- `.codex/archive/memory.md-20261027-213700.md` — immutable original full pre-#240 memory Git blob `72e0fe6912d3c19e46b2c11de4da532e24ed61fd` (all older commits/reviews/handoffs retained).
- `.codex/archive/memory.md-20261028-104900.md` — exact pre-reconciliation active memory Git blob `309b57f00fc85f0d03fd12fdb3b7bdfdaa4708d8`, including #240–#242 transitions and all superseded current-focus text.
- Original archive history for other five root memory files remains intact; the three new 2026-10-28 snapshots were SHA-matched before active rewriting. This is an intentional `AGENTS.md` archive-first compaction, not ordinary record deletion.

## 2026-10-28 #243 accepted; LLM call failure observed-time window (new independent branch)

- User-approved PR #243 merged on Hosted `main` `5c307705884903abca882f3283ec8968b302a2d4`, with formal Codex latest-head zero Findings/Threads and postmerge Hosted Linux `offline-e2e` #40628120579 SUCCESS (includes immutable archive test). Windows self-hosted Python 3.10/3.11 still queued; physical GUI/PSAPI/Ollama/ES acceptance not claimed. #231 independently OPEN and unchanged.
- New `feat/llm-failure-observed-time-window-20261028` reuses source-authoritative producer CSV `timestamp=datetime.now().isoformat(timespec="seconds")` (naive producer local clock) for optional `--since` (inclusive), `--before` (exclusive) in `czjLLM.cli_tools.llm_failure_report`; parse strict canonical seconds with no UTC/timezone guessing. Default absent filter is byte-for-byte equivalent report schema. When opted in, count only events in `[since,before)`, include optional bounded `time_window` metadata and per-run `excluded_by_time_window`; history isolates runs and keeps existing discovery/read budgets.
- Fail closed if filtered CSV has missing/duplicate timestamp header, malformed row width, missing/invalid/offset timestamp even if row is outside interval. Invalid input/report output never produces partial summary or discloses raw error, basename, prompt, endpoint or credential. Not a claim of stable request IDs, retries, unique logical failures, observed document failures, cross-host comparable absolute time or safe real-time mutable CSV.
- Added focused single/history boundary, source preservation, malformed/legacy, timestamp validation and privacy tests and usage docs. **Implementation committed; exact-head Hosted Linux E2E and formal Codex Review not yet accepted; no Merge authorized.**
