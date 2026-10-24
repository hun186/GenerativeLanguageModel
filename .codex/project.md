# GenerativeLanguageModel — Active Project Router

## Current Focus
- PR #225 Stage orchestration incidents merged. Current bounded P2: leaf Worker execution-phase exceptions (pre-call, API call site, response processing, result persistence), separate from request/slice/document denominators; lifecycle/filters remain later.
- Real Windows/Ollama/Elasticsearch smoke is a separate operator acceptance dependency.

## Recent Outcomes
- 2026-10-24 main baseline `e9a7e549205323b310ba7063cde5e39b0f5e1e01`; #219–#225 merged. PR #225 exact-head Linux `offline-e2e` + clean formal Codex Review; post-merge Linux offline-e2e run #39984570836 succeeded. Windows self-hosted remains operator-deferred.
- Issue #211 fixed via merged #212/#213 and closed after successful SQLite/Excel offline E2E; live provider acceptance not claimed.
- Reduction v1 release closure complete. Transient semantic cache #203 remains deferred.

## Open Handoffs
- Validate leaf Worker execution-phase incident PR at exact head: Linux offline E2E (including Worker phase tests), Codex P1/P2 and review threads; await explicit user merge approval.
- Define multi-stage Worker/Producer/Row Merger non-schema failure telemetry separately; drill-down and JSONL lifecycle remain pending.
- Operator: validate 1–3 real rows and independent ES readback before replaying the large workload.

## Load Routing
- Follow `AGENTS.md` first. Read this summary, `.codex/memory.md`, and task-relevant `.codex/backlog.md`, `.codex/known_issues.md`, `.codex/api_contract.md`, `.codex/architecture.md`, `.codex/decisions.md`.
- Hosted PR head, CI, Codex review and code override stale historical `pending` markers.
