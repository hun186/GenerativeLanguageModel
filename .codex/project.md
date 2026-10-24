# GenerativeLanguageModel — Active Project Router

## Current Focus
- PR #229 manual JSONL rotation and archive replay merged. Current bounded P2: explicitly opt-in SHA-256 consistency manifest for numbered JSONL archives, verified by read-only reports. Automated pruning and GUI live resume remain separate future tasks.
- Real Windows/Ollama/Elasticsearch smoke is a separate operator acceptance dependency.

## Recent Outcomes
- 2026-10-24 main baseline `638c0ddaa030e6d85de8f93e12f2360baf295802`; #219–#229 merged. #229 exact-head Linux `offline-e2e` and Codex 0 Findings; post-merge main Linux `offline-e2e` #40078552431 SUCCESS. Windows self-hosted remains operator-deferred.
- Issue #211 fixed via merged #212/#213 and closed after successful SQLite/Excel offline E2E; live provider acceptance not claimed.
- Reduction v1 release closure complete. Transient semantic cache #203 remains deferred.

## Open Handoffs
- Validate separate opt-in JSONL archive manifest PR at exact head: full Linux offline E2E including integrity/tamper regressions, clean Codex review, then await explicit user merge approval.
- Define multi-stage Worker/Producer/Row Merger non-schema failure telemetry separately; drill-down and JSONL lifecycle remain pending.
- Operator: validate 1–3 real rows and independent ES readback before replaying the large workload.

## Load Routing
- Follow `AGENTS.md` first. Read this summary, `.codex/memory.md`, and task-relevant `.codex/backlog.md`, `.codex/known_issues.md`, `.codex/api_contract.md`, `.codex/architecture.md`, `.codex/decisions.md`.
- Hosted PR head, CI, Codex review and code override stale historical `pending` markers.
