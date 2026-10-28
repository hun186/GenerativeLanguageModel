# GenerativeLanguageModel — Active Project Memory

## Current Summary

- **Authoritative state:** GitHub Hosted `main` SHA `46b7c7290417421a6dc09e114f82c1066ce0179d`; user-authorized PR #239 merged. Postmerge main Linux `offline-e2e` job in run #40513712390 **SUCCESS**. Entire workflow remains queued due to operator-deferred Windows 3.10/3.11 runners; never claim Windows GUI/PSAPI or live Ollama/ES acceptance from Linux CI.
- Repository `hun186/GenerativeLanguageModel` supports multi-source row/LLM processing (Table/Excel/CSV, SQL/SQLite, ES, local Ollama), output merge/writeback, Reduction Engine v1 and per-run quality observability. Root `AGENTS.md` and active `.codex/` are developer authority, but current code/Hosted PRs override historical memory labels.
- **Only other open PR at baseline:** #231, head `a8711e9337b62e4b9c6ad62f37ba3e78ba4e8fea`, OPEN, `mergeable=false`, unmerged; interrupted manual JSONL rotation rollback remains independent. Do NOT modify or merge it without explicit user authorization.
- **Merged/accepted:** #222–#230 (except independent #231), #232–#239, plus Issue #211 correction (#212/#213). Reduction Engine v1 A–L and v1.1 limited hook/lineage helpers accepted. Old “unmerged/pending Review” fragments in 2026-10-20–27 history have been superseded.
- Processing Quality v1 records strict privacy-minimal JSONL event observations at Consumer/Row Merger/Producer/Stage/leaf Worker boundaries; includes typed LLM SDK cause observations, read-only run incident drilldown, manual stopped-run segment rotation, trust-on-first-use SHA256 manifest, GUI cumulative archived+active reader with fail-closed capacity bounds, and opt-in offline exact temporary SQLite identity spill.
- Offline quality benchmark compares memory/SQLite full canonical report SHA256 over fresh children on stable stopped sources, with independent report call and parent-observed subprocess wall times, nullable OS high-water memory (Windows PSAPI peak working set), SQLite final DB size and strict finite numeric validation. This **does not** prove speedups, transactional log immutability, authenticated archive provenance or memory upper bounds.

## Recent Accepted PRs (2026-10-27)

| PR | User-approved merge on main | Evidence |
| --- | --- | --- |
| #233 | `8d4a967e29dbda8d845f30dde435e2883f9b9b3c` | GUI over-cap generation stat-cache; accepted |
| #234 | `4d34ac790a4511963d1b191cd495f459f9bee341` | Offline exact SQLite identity spill; accepted |
| #235 | `6cba3ef417047f07a2c3e8b46bd0ac36e7d2fd64` | Child-process resource benchmark; accepted |
| #236 | `6c5cda3b51fab14049edf540b65f30a59f2fb7ef` | Benchmark physical source-generation guard; accepted |
| #237 | `1757570e0c40d331d7a55ece386089309f13cd10` | Windows PeakWorkingSetSize PSAPI metric; accepted, Windows physical smoke deferred |
| #238 | `3cabaa4baa475d4d3566d552d6a5a53cae0fb1a8` | Parent subprocess wall-time metric; exact-head Codex zero findings/threads, PR Linux #40495454346 SUCCESS, postmerge Linux #40499018753 SUCCESS |
| #239 | `46b7c7290417421a6dc09e114f82c1066ce0179d` | Non-finite benchmark worker/parent numeric fail-closed checks; reviewed exact head `a973d7bcaef40856a01e24f89bb7e6555a5d7f62`, Codex 0 Findings/threads, PR Linux #40505732711 SUCCESS, postmerge Linux #40513712390 SUCCESS |

## Current Focus / Open Handoffs

- This independent documentation branch `docs/codex-active-memory-compaction-20261027` archives **exact** snapshots of active memory, architecture, API contract, decisions, backlog and known issues, then reduces stale historical acceptance notes. Archive Git blobs must equal original Git blobs. Run Linux CI/static checks and formal exact-head Codex Review; **no merge without explicit user approval**. Archive snapshots must be preserved verbatim.
- Keep #231 OPEN and independent. Separate future work: safe online rotation/retirement and crash-safe authenticated resume/checkpoint, bounded GUI restartable state, incident root-cause/denominator improvements, real 1–3 sample Windows/Ollama/ES persisted writeback/readback, and representative stopped-run PSAPI/performance benchmarking. No automatic pruning or file disposal is implemented.
- Do not misinterpret run-scoped catch-site incident event counts or the legacy request CSV as unique-document failure rates. Avoid raw private paths, keys, prompts, input payloads and error text in diagnostic outputs or commit history.

## Archived History

- `.codex/archive/memory.md-20261027-213700.md` — identical full pre-compaction memory text, Git blob `72e0fe6912d3c19e46b2c11de4da532e24ed61fd`, including earlier archive references, PR commitments, reviews, CI evidence, P1/P2 findings/remediations and superseded handoffs.
- The same timestamped verified-full-copy snapshot exists for `architecture.md`, `api_contract.md`, `decisions.md`, `backlog.md` and `known_issues.md`; previous archive files stay available.
- 2026-10-27 compaction verification: direct connector created archives **before** updating active versions, then confirmed each archive Git blob SHA and exact text match its original. No original history was discarded; the later PR tests recheck immutable snapshot blob IDs and the current actionable status.

## 2026-10-27 PR #240 first Codex Review P1/P2 remediation

- Formal Codex review of initial PR #240 exact HEAD `c614674644d35bcdc16ac47b685d2a00d145c0ff` completed with **1 P1** (active ES multidim date/precision + ES bulk acknowledgement contract missing after compaction) and **2 P2** (Windows `core.autocrlf` corrupts checkout-byte SHA assertions; new archive test absent from active Linux `offline-e2e` job). Initial Linux offline-e2e #40517361432 SUCCESS does **not** prove the new archive test ran.
- Remediation commits restore active ES date/precision atomic pair, Event[] referential integrity, and `confirm_writeback()` acknowledgement before Row Merger releases source/Success artifacts. Added targeted `.gitattributes` `-text` for the six immutable snapshot paths, enabled archive pytest in Linux `offline-e2e`, and added guard regressions for ES contract presence, cross-platform checkout byte stability, and CI invocation.
- Original six archived snapshots and their Git blob hashes remain unchanged. No runtime ES code or PR #231 changed.
- **Status:** remediation committed; verify new exact-head Linux CI, obtain *new* formal Codex Review and resolve three historical Review Threads after findings are confirmed addressed. Do not merge without explicit user approval.

## 2026-10-27 PR #240 second Codex Review (exact HEAD 8f780583) / P1 remediation

- Latest exact-head Codex Code Review of `8f780583ec5b97ee9924cdfea6edde7eb3539ce8` completed with **2 new P1 Findings**: (1) active single-extract `resume`/`smart_reset` full raw-source/slice-task provenance requirement missing after compaction; (2) active ES `importance` top-level five-score lossless integer/null normalization contract missing. Prior three Review Threads remain historically unresolved pending closure. Hosted Linux `offline-e2e` #40521614397 SUCCESS, including active archive regression step.
- Remediation restores full-source hash-only identity at `_extract_slice_identity/source/original.json`, ordered raw-slice/filename/dispatch/stage-task validation, refusal to infer complete membership from remaining TODO, verified child split provenance; restores `coverage`, `novelty`, `impact`, `credibility`, `importance_score` narrow lossless move and int-or-null, non-bool, no-conflict policy. Original six immutable archive blobs unchanged.
- New focused tests assert both current contracts remain in active docs. **Latest-head Hosted Linux CI and formal Codex re-review now pending; no merge authorization**. PR #231 remains OPEN/untouched; real Windows operator tests deferred.

## 2026-10-27 PR #240 third Codex Review (exact HEAD 7f53e817) / P2 remediation

- Third formal Codex Review of exact HEAD `7f53e8171034893554d1052b859f01c5e39a9dc1` completed with **one new P2**: still-current provider cache-aware LLM audit / stage-isolated GUI throughput contracts were archived but missing in active memory. Latest-head Linux offline-e2e #40525751547 SUCCESS (including archive integrity step); Windows physical self-hosted remains queued.
- Remediation restores `cached_input_tokens`, `cached_input_token_source`, `stage_identity`, `processing_tps`, `total_tok_per_s`, `effective_tok_per_s_est` in active contract/architecture/decisions; explicitly distinguishes provider-reported zero vs unknown, separates provider samples from two-prior-stable-template heuristic, requires same model/endpoint/task/stage/source and at most 50% proxy discount. Adds `test_cache_aware_provider_audit_and_stage_isolated_gui_are_active`.
- **Fourth exact-head Hosted CI and formal Codex Review pending.** Six immutable archives and all runtime product code are untouched, PR #231 independent OPEN; do not merge PR #240 without user approval.

## 2026-10-28 PR #240 merged; next quality report output ledger protection

- User-authorized PR #240 merge verified in Hosted main `21ae2cb690031c6409fd05f5cf6e4109a21548e1`. Formal Codex reviewed exact head `d284f15da4e7bcbde8c7b0bac7f68f0fc1e968f8`: Completed, 0 Findings, 6/6 threads resolved. PR Linux `offline-e2e` #40530750923 SUCCESS including archive test; postmerge main Linux `offline-e2e` #40604470304 SUCCESS. Windows self-hosted queued; no Windows/LLM/ES production acceptance claim. Independent PR #231 remains OPEN.
- New branch `fix/quality-report-protect-manifest-output-20261028` based on this merged main. Identified destructive CLI path: `czjLLM.cli_tools.processing_quality_report --output <processing_quality_events_*.jsonl.manifest.json>` previously allowed any `.json`; `atomic_write_json` uses `os.replace`, so a read-only summary could overwrite the authoritative sealed archive consistency ledger (even for another run), damaging verification/history.
- Implemented narrowly scoped fail-fast `_validate_report_output_path` before replay or temporary SQLite index: refuse `processing_quality_events_*.jsonl.manifest.json` (including absent reserved destinations / Windows-case variants) and symlink output aliases; preserve normal separate `quality_summary.json` writing and existing report v1 metrics/CLI interfaces.
- New real-file tests create/seal multiple quality event streams, verify own/other manifest bytes remain byte-for-byte intact after refused single-run/history exports, check reserved absent destinations and symlinks, and independently verify previously sealed archives remain readable. Usage docs updated.
- **Status: implementation/test/docs committed on branch; exact-head Hosted Linux `offline-e2e` and formal Codex Review not yet accepted. PR requires explicit merge authorization; PR #231 independent untouched.**
