# GenerativeLanguageModel — Active Project Router

## Current Focus
- PR #224 Producer operational events merged. Current bounded P2: Stage orchestration prepare/runner escaped exceptions, separate from request/slice/document denominators; lifecycle/filters remain later.
- Real Windows/Ollama/Elasticsearch smoke is a separate operator acceptance dependency.

## Recent Outcomes
- 2026-10-23 main baseline `06a17d48442cce645a8e429e4a6e083fc9679692`; #219–#224 merged. PR #224 exact-head Linux `offline-e2e`, formal Codex Review and all threads passed; post-merge main Linux offline-e2e job in run #39980110881 succeeded. Windows self-hosted is operator-deferred.
- Issue #211 fixed via merged #212/#213 and closed after successful SQLite/Excel offline E2E; live provider acceptance not claimed.
- Reduction v1 release closure complete. Transient semantic cache #203 remains deferred.

## Open Handoffs
- Validate Stage orchestration incident PR at exact head: Linux offline E2E (including stage orchestration tests), Codex P1/P2 and review threads; await explicit user merge approval.
- Define multi-stage Worker/Producer/Row Merger non-schema failure telemetry separately; drill-down and JSONL lifecycle remain pending.
- Operator: validate 1–3 real rows and independent ES readback before replaying the large workload.

## Load Routing
- Follow `AGENTS.md` first. Read this summary, `.codex/memory.md`, and task-relevant `.codex/backlog.md`, `.codex/known_issues.md`, `.codex/api_contract.md`, `.codex/architecture.md`, `.codex/decisions.md`.
- Hosted PR head, CI, Codex review and code override stale historical `pending` markers.
