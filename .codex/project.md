# GenerativeLanguageModel — Active Project Router

## Current Focus
- PR #227 typed SDK call-site incidents merged. Current bounded P2: read-only run-scoped incident code drilldown and allowlisted family filters using existing JSONL, with accurate incident-event denominators; lifecycle/retention remain later.
- Real Windows/Ollama/Elasticsearch smoke is a separate operator acceptance dependency.

## Recent Outcomes
- 2026-10-24 main baseline `45a6b6e663f1bbe1ad30eccd403f593b0860de1c`; #219–#227 merged. PR #227 exact-head Linux `offline-e2e` + clean formal Codex Review; post-merge Linux run #40070824184 was in progress when this branch started. Windows self-hosted remains operator-deferred.
- Issue #211 fixed via merged #212/#213 and closed after successful SQLite/Excel offline E2E; live provider acceptance not claimed.
- Reduction v1 release closure complete. Transient semantic cache #203 remains deferred.

## Open Handoffs
- Validate independent run-only incident drilldown PR at exact head: Linux offline E2E (including new report filters), Codex P1/P2 and review threads; await explicit user merge approval.
- Define multi-stage Worker/Producer/Row Merger non-schema failure telemetry separately; drill-down and JSONL lifecycle remain pending.
- Operator: validate 1–3 real rows and independent ES readback before replaying the large workload.

## Load Routing
- Follow `AGENTS.md` first. Read this summary, `.codex/memory.md`, and task-relevant `.codex/backlog.md`, `.codex/known_issues.md`, `.codex/api_contract.md`, `.codex/architecture.md`, `.codex/decisions.md`.
- Hosted PR head, CI, Codex review and code override stale historical `pending` markers.
