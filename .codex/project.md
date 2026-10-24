# GenerativeLanguageModel — Active Project Router

## Current Focus
- PR #228 run-scoped incident drilldown merged. Current bounded P2: explicit stopped-producer non-deleting JSONL archive rotation and offline cross-segment replay. Auto-retention, durable manifest and GUI live resume are independent future tasks.
- Real Windows/Ollama/Elasticsearch smoke is a separate operator acceptance dependency.

## Recent Outcomes
- 2026-10-24 main baseline `2fdae2bab465471ddb88cbf574c2d6a2b44a0f46`; #219–#228 merged. PR #228 exact-head Linux `offline-e2e` and formal Codex completed with 0 Findings; post-merge main CI #40074000439 was in progress when the new branch began. Windows self-hosted remains operator-deferred.
- Issue #211 fixed via merged #212/#213 and closed after successful SQLite/Excel offline E2E; live provider acceptance not claimed.
- Reduction v1 release closure complete. Transient semantic cache #203 remains deferred.

## Open Handoffs
- Validate separate non-deleting JSONL rotation and offline replay PR at exact head: full Linux offline E2E including rotation regression, clean Codex review, then wait for explicit user merge approval.
- Define multi-stage Worker/Producer/Row Merger non-schema failure telemetry separately; drill-down and JSONL lifecycle remain pending.
- Operator: validate 1–3 real rows and independent ES readback before replaying the large workload.

## Load Routing
- Follow `AGENTS.md` first. Read this summary, `.codex/memory.md`, and task-relevant `.codex/backlog.md`, `.codex/known_issues.md`, `.codex/api_contract.md`, `.codex/architecture.md`, `.codex/decisions.md`.
- Hosted PR head, CI, Codex review and code override stale historical `pending` markers.
