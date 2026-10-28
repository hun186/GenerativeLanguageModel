# GenerativeLanguageModel — Active Project Router

## Current Focus

- **Current accepted main:** User-approved PR #241 merged as `fb713365b173378ba8ca82e0557e4fdd5a415650`; main Hosted Linux `offline-e2e` #40616682036 SUCCESS. Formal Codex exact-head #241 completed zero Findings, one historical P2 thread resolved; Windows 3.10/3.11 operator-deferred. Older #240/#241 "pending review/merge" labels below are historical, not current.
- **Independent next branch:** `fix/llm-failure-report-cross-dir-ledger-output-20261028` plugs a matching read-only `llm_failure_report --output` integrity risk: destination reserved `processing_quality_events_*.jsonl.manifest.json` in **another directory** bypassed previous same-source-dir guard. Now refuses the reserved pattern globally and checks output before private CSV replay; normal report-v1 JSON and existing safe in-folder artifact restrictions remain. Actual-file tests, docs, CI and formal Codex Review required; **do not merge without explicit approval**. PR #231 OPEN/untouched.


- **2026-10-28 authoritative GitHub reconciliation:** User-approved PR #240 has **merged**, main merge SHA `21ae2cb690031c6409fd05f5cf6e4109a21548e1`; formal Codex fourth exact-head review completed with zero Findings, 6/6 review threads resolved, postmerge Hosted Linux `offline-e2e` #40604470304 SUCCESS. All older statements below about PR #240 being unmerged or pending review are historical/superseded. Windows 3.10/3.11 self-hosted remain queued/operator-deferred.
- **New independent focus (no merge authorization):** `fix/quality-report-protect-manifest-output-20261028` prevents the read-only offline Quality Report CLI `--output` from atomically replacing any `processing_quality_events_*.jsonl.manifest.json` integrity ledger, or a symlink output alias; reject before source replay, preserve strict sealed-archive SHA256 and report_version=1. Add real-file and negative-path tests; require new exact-head Hosted Linux CI and formal Codex Review before asking the user to merge. Existing PR #231 independent OPEN/unchanged.


- **Accepted Hosted main:** `46b7c7290417421a6dc09e114f82c1066ce0179d` (user-approved PR #239 merge). Postmerge Hosted Linux `offline-e2e` #40513712390 SUCCESS; Windows self-hosted Python 3.10/3.11 **queued and operator-deferred**, so do not claim full workflow success or physical Windows/Ollama/ES verification.
- **This independent PR:** `docs/codex-active-memory-compaction-20261027` performs the `AGENTS.md`-mandated six-file archive-first memory compaction. The old full original `.codex/*.md` versions are saved byte-for-byte under `.codex/archive/*-20261027-213700.md` with matching Git Blob SHA before replacement. Active files now contain current contracts and open constraints. Initial review found 1 P1 + 2 P2 (restored ES date/bulk contracts, immutable archive LF/CRLF, active Linux archive CI gate). Second exact-head review `8f780583ec5b97ee9924cdfea6edde7eb3539ce8` found 2 new P1 (original single-extract resume source identity, strict ES importance-score normalization); now fixed with active contracts and guard tests. Latest-head Linux CI and fresh Codex review remain required; 5 historical review threads need evidence-backed resolution. **No merge until the user explicitly authorizes it**.
- **Independent PR #231:** OPEN, head `a8711e9337b62e4b9c6ad62f37ba3e78ba4e8fea`, previously `mergeable=false`. Do not edit, close, rebase or merge it in this work.

- Third exact-head Codex Review `7f53e8171034893554d1052b859f01c5e39a9dc1` found 1 P2: active cache-aware audit/GUI throughput semantics had been accidentally archived. Restored `cached_input_tokens`, `cached_input_token_source`, `stage_identity`, provider/heuristic distinctions, `total_tok_per_s`/`effective_tok_per_s_est`, unchanged `processing_tps`, stage-specific history and positive-duration boundaries; added regression. Latest-head Linux CI + fourth formal Codex re-review and evidence-backed closure of prior review threads needed before merge.

## Recent Accepted Outcomes

- #233 GUI over-cap replay generation guard merged `8d4a967e29dbda8d845f30dde435e2883f9b9b3c`.
- #234 opt-in offline exact SQLite spill merged `4d34ac790a4511963d1b191cd495f459f9bee341`.
- #235 fresh subprocess resource benchmark merged `6cba3ef417047f07a2c3e8b46bd0ac36e7d2fd64`.
- #236 stopped-run source-generation guard merged `6c5cda3b51fab14049edf540b65f30a59f2fb7ef`.
- #237 Windows PSAPI historical working-set peak merged `1757570e0c40d331d7a55ece386089309f13cd10`; real Windows smoke still pending.
- #238 parent-measured child lifecycle wall time merged `3cabaa4baa475d4d3566d552d6a5a53cae0fb1a8`. Codex exact head clean, Linux PR #40495454346 and postmerge #40499018753 successful offline-e2e jobs.
- #239 non-finite benchmark numeric/JSON validation merged `46b7c7290417421a6dc09e114f82c1066ce0179d`. Exact HEAD `a973d7bcaef40856a01e24f89bb7e6555a5d7f62` Codex completed 0 Findings/Threads, PR Linux #40505732711 and main Linux #40513712390 SUCCESS.
- Previous quality event/GUI/manifest PRs #218–#230 (except #231) and #232 accepted. Issue #211 resolved by #212/#213 and focused offline E2E; no live service acceptance claim. Reduction Engine v1 release closure is complete. #203 transient cache remains deferred.

## Open Handoffs

- Operator: benchmark representative stopped real quality streams under Windows (including actual PSAPI behavior); inspect GUI with real Windows/Tk and 1–3 controlled Ollama/ES writebacks with independent ES readback before any large production replay.
- Engineering separate scopes: fix PR #231's interrupted rotation branch only with fresh mergeability evidence and user approval; truly crash-safe authenticated checkpoint/replay, safe online rotation/automated pruning, bounded GUI restartable state, and real logical retry denominators/error attribution. Existing temp SQLite, manifest SHA256, event catch-site counts and Linux CI do not establish those properties.
- Old literal “new PR pending” histories have moved to immutable archives. Do not revive them as unfinished without reconciling current Hosted main/PR state. No unauthorized merge or destructive input/archive changes.

## Load Routing

- Read root `AGENTS.md`, then `.codex/project.md` and the task-relevant **active** `.codex/memory.md`, `.codex/architecture.md`, `.codex/api_contract.md`, `.codex/known_issues.md`, `.codex/decisions.md`, `.codex/backlog.md`.
- Old full history is indexed by each active document's `Archived History`; load the corresponding `.codex/archive/*-20261027-213700.md` only for concrete traceability or resolving differences, never for routine context.
- Current GitHub HEAD, Hosted CI, code and official Codex Reviews override any historical stale acceptance marker.
