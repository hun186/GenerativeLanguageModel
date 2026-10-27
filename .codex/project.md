# GenerativeLanguageModel — Active Project Router

## Current Focus
- PR #238 benchmark parent-observed per-child wall timing **merged**, postmerge main Linux offline-e2e SUCCESS. Next focus: reject non-finite or ill-typed child benchmark values at the process boundary, prevent invalid published JSON and preserve privacy-safe errors. Real Windows PSAPI and representative workload acceptance remain operator-deferred; PR #231 stays independent/open.
- Real Windows/Ollama/Elasticsearch smoke is a separate operator acceptance dependency.

## Recent Outcomes
- 2026-10-27 PR #238 user-authorized merge `3cabaa4baa475d4d3566d552d6a5a53cae0fb1a8` verified on main. Accepted HEAD `ce48c00520927016bf57942e66808250b0d5afbd`, formal Codex zero findings/threads, PR Linux offline-e2e #40495454346 SUCCESS, main postmerge offline-e2e #40499018753 SUCCESS. Windows self-hosted queued; overall workflow not SUCCESS. Next branch starts from this accepted main.
- 2026-10-27 PR #237 user-authorized merge `1757570e0c40d331d7a55ece386089309f13cd10`, reviewed exact HEAD `4bd0bfbf15f6a1d9285e2cc6064a61771e169779`: formal Codex completed zero findings/threads, latest-head Linux PR offline-e2e #40483598995 SUCCESS, main postmerge Linux offline-e2e #40491920298 SUCCESS. Windows selfhosted queued/operator-deferred; overall run pending, not a Windows acceptance claim. Next per-child subprocess wall-cost measurement branch begins from accepted main. PR #231 unchanged/open.
- 2026-10-27 user-approved PR #236 merge `6c5cda3b51fab14049edf540b65f30a59f2fb7ef` verified on main. Reviewed exact HEAD `0f4012b16fe6c1ad2ce5840eacd1e2655f027920`, formal Codex 0 Findings/Threads, latest-head PR Linux offline-e2e #40468583534 SUCCESS; main postmerge Linux offline-e2e #40470719085 SUCCESS. Windows self-hosted queued/operator-deferred; full workflow queued. New Windows benchmark metric branch starts from accepted main.
- 2026-10-27 user-authorized PR #235 merge `6cba3ef417047f07a2c3e8b46bd0ac36e7d2fd64` is on main. Exact HEAD `9534a9497ba7becf4bafe5cc8fe861cfd33d8467` passed formal Codex with 0 findings and two resolved P1/P2 threads, PR Linux offline-e2e #40462916581 SUCCESS, postmerge Linux offline-e2e #40465197165 SUCCESS. Windows queued/operator deferred; overall workflow not SUCCESS. Next branch begins from accepted main. PR #231 remains open, unmerged and mergeable=false.
- 2026-10-27 PR #234 user-authorized merge `4d34ac790a4511963d1b191cd495f459f9bee341`, exact HEAD `63e59187...`: formal Codex review completed clean on latest HEAD, historical P2 threads resolved, PR Linux offline-e2e #40374056931 SUCCESS; postmerge main Linux `offline-e2e` #40421390604 SUCCESS, Windows queued and unit-linux skipped. New benchmark branch starts from accepted main; Hosted CI/Review pending.
- 2026-10-27 PR #233 merge `8d4a967e29dbda8d845f30dde435e2883f9b9b3c` verified main; original HEAD `0072cda7...` Codex completed with zero findings/threads. Postmerge Hosted Linux `offline-e2e` #40360012110 SUCCESS (overall workflow queued for operator-deferred Windows). New disk-spill branch based only on accepted main; its CI and review are pending.
- 2026-10-25 main baseline `324148f7d747be8afbddb4c6a448d053b0255e2c`; #219–#230 and #232 merged. #232 latest head Codex 0 Findings/threads, PR Linux `offline-e2e` #40092679536 SUCCESS and main postmerge Linux #40101418772 SUCCESS. #231 remains OPEN and unmerged; Windows self-hosted deferred.
- Issue #211 fixed via merged #212/#213 and closed after successful SQLite/Excel offline E2E; live provider acceptance not claimed.
- Reduction v1 release closure complete. Transient semantic cache #203 remains deferred.

## Open Handoffs
- Keep PR #231 OPEN until user explicitly authorizes merge; it currently reports mergeable=false. Verify finite-measurements defensive regression branch at exact latest HEAD (NaN/Infinity, exponent overflow, byte-count types and parent wall clock) with Hosted Linux offline-e2e and formal Codex Review. Merge only after user's authorization. Windows native PSAPI and real stopped-run benchmarks still operator-deferred; no persistent checkpoint, auto retention or online writer-safe mode.
- Define multi-stage Worker/Producer/Row Merger non-schema failure telemetry separately; drill-down and JSONL lifecycle remain pending.
- Operator: validate 1–3 real rows and independent ES readback before replaying the large workload.

## Load Routing
- Follow `AGENTS.md` first. Read this summary, `.codex/memory.md`, and task-relevant `.codex/backlog.md`, `.codex/known_issues.md`, `.codex/api_contract.md`, `.codex/architecture.md`, `.codex/decisions.md`.
- Hosted PR head, CI, Codex review and code override stale historical `pending` markers.
