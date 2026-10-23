# GenerativeLanguageModel — Active Project Router

## Current Focus
- PR #223 Row Merger non-schema retry events merged. Current bounded P2: Producer operational catch-site events (schedule, backpressure, future) separate from request/slice/document denominators; Stage Worker is later.
- Real Windows/Ollama/Elasticsearch smoke is a separate operator acceptance dependency.

## Recent Outcomes
- 2026-10-23 main baseline `a9240f826bfef9a999848017a254c69c5c05f748`; #219–#223 merged. PR #223 exact-head Linux `offline-e2e` passed, formal Codex review clean and all review threads resolved. Post-merge Linux CI #39974457753 is a distinct gate; Windows self-hosted unavailable and operator explicitly defers Windows acceptance.
- Issue #211 fixed via merged #212/#213 and closed after successful SQLite/Excel offline E2E; live provider acceptance not claimed.
- Reduction v1 release closure complete. Transient semantic cache #203 remains deferred.

## Open Handoffs
- Validate Producer operational incident PR at exact head: Linux offline E2E (including producer caught-failure tests), Codex P1/P2 and review threads; await explicit user merge approval.
- Define multi-stage Worker/Producer/Row Merger non-schema failure telemetry separately; drill-down and JSONL lifecycle remain pending.
- Operator: validate 1–3 real rows and independent ES readback before replaying the large workload.

## Load Routing
- Follow `AGENTS.md` first. Read this summary, `.codex/memory.md`, and task-relevant `.codex/backlog.md`, `.codex/known_issues.md`, `.codex/api_contract.md`, `.codex/architecture.md`, `.codex/decisions.md`.
- Hosted PR head, CI, Codex review and code override stale historical `pending` markers.
