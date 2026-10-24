# GenerativeLanguageModel — Active Project Router

## Current Focus
- PR #226 leaf Worker execution-phase incidents merged. Current bounded P2: classify typed OpenAI SDK errors inside existing Worker call-site incident (timeout/connection/HTTP/validation), without changing denominators; lifecycle/filters remain later.
- Real Windows/Ollama/Elasticsearch smoke is a separate operator acceptance dependency.

## Recent Outcomes
- 2026-10-24 main baseline `a4eb5ec3fcb68eb07ae849f77294cc8b72a59b24`; #219–#226 merged. PR #226 exact-head Linux `offline-e2e` + clean formal Codex Review; post-merge Linux offline-e2e run #40066964887 succeeded. Windows self-hosted remains operator-deferred.
- Issue #211 fixed via merged #212/#213 and closed after successful SQLite/Excel offline E2E; live provider acceptance not claimed.
- Reduction v1 release closure complete. Transient semantic cache #203 remains deferred.

## Open Handoffs
- Validate typed-SDK Worker incident subtype PR at exact head: Linux offline E2E (including real SDK mock-transport tests), Codex P1/P2 and review threads; await explicit user merge approval.
- Define multi-stage Worker/Producer/Row Merger non-schema failure telemetry separately; drill-down and JSONL lifecycle remain pending.
- Operator: validate 1–3 real rows and independent ES readback before replaying the large workload.

## Load Routing
- Follow `AGENTS.md` first. Read this summary, `.codex/memory.md`, and task-relevant `.codex/backlog.md`, `.codex/known_issues.md`, `.codex/api_contract.md`, `.codex/architecture.md`, `.codex/decisions.md`.
- Hosted PR head, CI, Codex review and code override stale historical `pending` markers.
