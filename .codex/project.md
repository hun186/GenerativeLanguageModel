# GenerativeLanguageModel — Active Project Router

## Current Focus
- PR #222 Consumer orchestration run events merged. Next bounded P2: Row Merger non-schema retry observations without mixing request/slice/document denominators.
- Real Windows/Ollama/Elasticsearch smoke is a separate operator acceptance dependency.

## Recent Outcomes
- 2026-10-23 main baseline `bd3fc22c647ef296c2210750a69c78c168c50904`; #219–#222 merged. Post-merge Linux `offline-e2e` succeeded. Windows self-hosted unavailable: operator explicitly skips Windows validation for now.
- Issue #211 fixed via merged #212/#213 and closed after successful SQLite/Excel offline E2E; live provider acceptance not claimed.
- Reduction v1 release closure complete. Transient semantic cache #203 remains deferred.

## Open Handoffs
- Validate next Row Merger PR at exact head: Linux offline E2E, Codex review, P1/P2 findings and review threads; await user merge approval.
- Define multi-stage Worker/Producer/Row Merger non-schema failure telemetry separately; drill-down and JSONL lifecycle remain pending.
- Operator: validate 1–3 real rows and independent ES readback before replaying the large workload.

## Load Routing
- Follow `AGENTS.md` first. Read this summary, `.codex/memory.md`, and task-relevant `.codex/backlog.md`, `.codex/known_issues.md`, `.codex/api_contract.md`, `.codex/architecture.md`, `.codex/decisions.md`.
- Hosted PR head, CI, Codex review and code override stale historical `pending` markers.
