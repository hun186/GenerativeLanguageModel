# GenerativeLanguageModel — Active Project Router

## Current Focus
- PR #230 opt-in SHA-256 JSONL archive consistency manifest merged. Current bounded P2: inspect and manually roll back only one unsealed extra archive from a verified interrupted rotation; defer other crash states, auto retention and GUI resume.
- Real Windows/Ollama/Elasticsearch smoke is a separate operator acceptance dependency.

## Recent Outcomes
- 2026-10-24 main baseline `14f89017092f98374406a6512b5dd1dd21c1cb78`; #219–#230 merged. #230 exact-head Codex 0 Findings and PR Linux `offline-e2e` SUCCESS; post-merge main Linux `offline-e2e` #40083669550 SUCCESS. Windows self-hosted remains operator-deferred.
- Issue #211 fixed via merged #212/#213 and closed after successful SQLite/Excel offline E2E; live provider acceptance not claimed.
- Reduction v1 release closure complete. Transient semantic cache #203 remains deferred.

## Open Handoffs
- Validate independent interrupted rotation inspection/manual no-clobber rollback PR at exact head: full Linux offline E2E with real crash-window regressions and formal Codex review; await explicit user merge approval.
- Define multi-stage Worker/Producer/Row Merger non-schema failure telemetry separately; drill-down and JSONL lifecycle remain pending.
- Operator: validate 1–3 real rows and independent ES readback before replaying the large workload.

## Load Routing
- Follow `AGENTS.md` first. Read this summary, `.codex/memory.md`, and task-relevant `.codex/backlog.md`, `.codex/known_issues.md`, `.codex/api_contract.md`, `.codex/architecture.md`, `.codex/decisions.md`.
- Hosted PR head, CI, Codex review and code override stale historical `pending` markers.
