# GenerativeLanguageModel — Active Project Memory

## Current Summary

- **Historical #242 accepted main:** `e010a5e07c45016f8f0ab4094c30bcd33825d3b5` (user-approved PR #242 merge, 2026-10-28). PR #242 formal exact-head Codex Review completed with zero Findings/Threads and Hosted Linux `offline-e2e` #40622149444 SUCCESS. Postmerge main Linux `offline-e2e` #40623677955 **SUCCESS**, including immutable archive test, verified on Hosted GitHub. Windows 3.10/3.11 are queued/operator-deferred, so real Windows GUI/PSAPI/LLM/SQL/ES is not accepted.
- Repository `hun186/GenerativeLanguageModel` supports tabular SQL/SQLite/ES and LLM multi-stage processing, merged/writeback outputs, Reduction Engine v1 and privacy-minimal per-run observability. Effective contracts live in active `.codex/{architecture,api_contract,decisions,known_issues}.md`, runtime implementation and tests; old chronology is in immutable archives.
- **#231 was later merged**; the former open-stage details remain in immutable archive memory.md-20261030-103500.md. Remaining runtime recovery issues stay separately gated.
- **Current security handoff:** Hosted main before PR #258: 8b12a8916948f075b4cab9f03949b5306f6db49a. PR #258 remains OPEN, independent #254 remains outside scope; refresh Hosted status before merging.

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

- Preserve source and audit identity correctness; queue/recovery work is separate from PR #258.
- Validate completed vs deferred states from current GitHub and operator evidence before preparing reports or starting new PRs.

## Archived History

- `.codex/archive/memory.md-20261027-213700.md` — immutable original full pre-#240 memory Git blob `72e0fe6912d3c19e46b2c11de4da532e24ed61fd` (all older commits/reviews/handoffs retained).
- `.codex/archive/memory.md-20261028-104900.md` — exact pre-reconciliation active memory Git blob `309b57f00fc85f0d03fd12fdb3b7bdfdaa4708d8`, including #240–#242 transitions and all superseded current-focus text.
- Original archive history for other five root memory files remains intact; the three new 2026-10-28 snapshots were SHA-matched before active rewriting. This is an intentional `AGENTS.md` archive-first compaction, not ordinary record deletion.

## Current security work — 2026-10-30
- Current PR #258 is OPEN. This branch untracks 4 SQL and 7 Elasticsearch connection profile files and keeps 11 shareable .py.example templates. Private complete profiles belong in czjLLM/config_sql/private/ and czjLLM/config_es/private/; the user reports backing up both directories outside the repository.
- The private profile resolver and menu retain legacy YAML path compatibility. The optional local migration tool copies files without deleting originals, with atomic no-overwrite publication and a synthetic regression. Actual operator credentials and service connectivity have not been tested.
- Previously merged #255, #256, #257 improved current-source credential handling, history read-only inventory and approval-gated planning. User reports the previous DeepSeek key revoked. Historical cleanup is deferred.
- Queue and quality changes from #243 through #252 remain preserved in the archive below; exact PR reviews and CI must be consulted before further changes.

## New archive
- The complete prior active memory was saved verbatim at .codex/archive/memory.md-20261030-103500.md, original Git blob 8af2694365bd5202a1533a36c8b7cd4c82f22408.
- Earlier immutable archives and references above remain unchanged. The previous Linux E2E failed because active memory exceeded 40 KB. Latest PR CI and formal review require new validation before merge.
