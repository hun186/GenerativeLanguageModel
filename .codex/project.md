# GenerativeLanguageModel — Active Project Router

## Current Focus
- PR #235 real-run offline quality performance and parity benchmark **merged**, postmerge Linux offline-e2e SUCCESS. Next independent focus: read-only physical source-generation checks across active JSONL, shards and manifest for that benchmark, including same-digest source drift detection. No archive deletion or producer changes; PR #231 remains independent/open.
- Real Windows/Ollama/Elasticsearch smoke is a separate operator acceptance dependency.

## Recent Outcomes
- 2026-10-27 user-authorized PR #235 merge `6cba3ef417047f07a2c3e8b46bd0ac36e7d2fd64` is on main. Exact HEAD `9534a9497ba7becf4bafe5cc8fe861cfd33d8467` passed formal Codex with 0 findings and two resolved P1/P2 threads, PR Linux offline-e2e #40462916581 SUCCESS, postmerge Linux offline-e2e #40465197165 SUCCESS. Windows queued/operator deferred; overall workflow not SUCCESS. Next branch begins from accepted main. PR #231 remains open, unmerged and mergeable=false.
- 2026-10-27 PR #234 user-authorized merge `4d34ac790a4511963d1b191cd495f459f9bee341`, exact HEAD `63e59187...`: formal Codex review completed clean on latest HEAD, historical P2 threads resolved, PR Linux offline-e2e #40374056931 SUCCESS; postmerge main Linux `offline-e2e` #40421390604 SUCCESS, Windows queued and unit-linux skipped. New benchmark branch starts from accepted main; Hosted CI/Review pending.
- 2026-10-27 PR #233 merge `8d4a967e29dbda8d845f30dde435e2883f9b9b3c` verified main; original HEAD `0072cda7...` Codex completed with zero findings/threads. Postmerge Hosted Linux `offline-e2e` #40360012110 SUCCESS (overall workflow queued for operator-deferred Windows). New disk-spill branch based only on accepted main; its CI and review are pending.
- 2026-10-25 main baseline `324148f7d747be8afbddb4c6a448d053b0255e2c`; #219–#230 and #232 merged. #232 latest head Codex 0 Findings/threads, PR Linux `offline-e2e` #40092679536 SUCCESS and main postmerge Linux #40101418772 SUCCESS. #231 remains OPEN and unmerged; Windows self-hosted deferred.
- Issue #211 fixed via merged #212/#213 and closed after successful SQLite/Excel offline E2E; live provider acceptance not claimed.
- Reduction v1 release closure complete. Transient semantic cache #203 remains deferred.

## Open Handoffs
- Keep PR #231 OPEN until user explicitly authorizes merge; it currently reports mergeable=false. Verify independent benchmark source-generation guard branch at exact HEAD with actual-file mutation/manifest/shard/symlink regression and Hosted Linux plus formal Codex Review; no merge without explicit user authorization. The guard is not a file lock or content authentication. No persistent checkpoint, automatic pruning or live-source benchmarking in this phase.
- Define multi-stage Worker/Producer/Row Merger non-schema failure telemetry separately; drill-down and JSONL lifecycle remain pending.
- Operator: validate 1–3 real rows and independent ES readback before replaying the large workload.

## Load Routing
- Follow `AGENTS.md` first. Read this summary, `.codex/memory.md`, and task-relevant `.codex/backlog.md`, `.codex/known_issues.md`, `.codex/api_contract.md`, `.codex/architecture.md`, `.codex/decisions.md`.
- Hosted PR head, CI, Codex review and code override stale historical `pending` markers.
