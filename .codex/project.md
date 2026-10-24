# GenerativeLanguageModel — Active Project Router

## Current Focus
- PR #229 manual JSONL rotation and archive replay merged. Current bounded P2: explicitly opt-in SHA-256 consistency manifest for numbered JSONL archives, verified by read-only reports. Automated pruning and GUI live resume remain separate future tasks.
- Real Windows/Ollama/Elasticsearch smoke is a separate operator acceptance dependency.

## Recent Outcomes
- 2026-10-24 main baseline `14f89017092f98374406a6512b5dd1dd21c1cb78`; #219–#230 merged. #230 postmerge main Linux `offline-e2e` #40083669550 SUCCESS. #231 latest exact-head `a8711e9337b62e4b9c6ad62f37ba3e78ba4e8fea` Codex 0 Findings/threads and Linux `offline-e2e` #40086132477 SUCCESS, **OPEN/not merged**. Windows self-hosted deferred.
- Issue #211 fixed via merged #212/#213 and closed after successful SQLite/Excel offline E2E; live provider acceptance not claimed.
- Reduction v1 release closure complete. Transient semantic cache #203 remains deferred.

## Open Handoffs
- Keep PR #231 OPEN until user explicitly approves merge. Validate independent GUI multi-shard cumulative reader PR at exact HEAD: Linux offline-E2E including background-reader tests, formal Codex P1/P2 review, then await explicit user merge approval.
- Define multi-stage Worker/Producer/Row Merger non-schema failure telemetry separately; drill-down and JSONL lifecycle remain pending.
- Operator: validate 1–3 real rows and independent ES readback before replaying the large workload.

## Load Routing
- Follow `AGENTS.md` first. Read this summary, `.codex/memory.md`, and task-relevant `.codex/backlog.md`, `.codex/known_issues.md`, `.codex/api_contract.md`, `.codex/architecture.md`, `.codex/decisions.md`.
- Hosted PR head, CI, Codex review and code override stale historical `pending` markers.
