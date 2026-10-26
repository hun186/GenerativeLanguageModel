# GenerativeLanguageModel — Active Project Router

## Current Focus
- PR #233 GUI finite quality retention/cardinality/JSONL-line safeguards **merged and accepted by Linux offline-e2e**. Current independent next stage: opt-in temporary SQLite-backed exact offline identity accumulation for large JSONL history, without changing GUI caps or allowing archive deletion. PR #231 crash rollback remains separate and unmerged.
- Real Windows/Ollama/Elasticsearch smoke is a separate operator acceptance dependency.

## Recent Outcomes
- 2026-10-27 PR #233 merge `8d4a967e29dbda8d845f30dde435e2883f9b9b3c` verified main; original HEAD `0072cda7...` Codex completed with zero findings/threads. Postmerge Hosted Linux `offline-e2e` #40360012110 SUCCESS (overall workflow queued for operator-deferred Windows). New disk-spill branch based only on accepted main; its CI and review are pending.
- 2026-10-25 main baseline `324148f7d747be8afbddb4c6a448d053b0255e2c`; #219–#230 and #232 merged. #232 latest head Codex 0 Findings/threads, PR Linux `offline-e2e` #40092679536 SUCCESS and main postmerge Linux #40101418772 SUCCESS. #231 remains OPEN and unmerged; Windows self-hosted deferred.
- Issue #211 fixed via merged #212/#213 and closed after successful SQLite/Excel offline E2E; live provider acceptance not claimed.
- Reduction v1 release closure complete. Transient semantic cache #203 remains deferred.

## Open Handoffs
- Keep PR #231 OPEN until user explicitly authorizes merge; it currently reports mergeable=false and is not part of the next work. Verify new offline disk-spill PR at exact HEAD via Hosted Linux, focused actual-file parity tests and Codex Review; no merge without explicit user authorization. No persistent checkpoint, automatic deletion or signed manifest in this phase.
- Define multi-stage Worker/Producer/Row Merger non-schema failure telemetry separately; drill-down and JSONL lifecycle remain pending.
- Operator: validate 1–3 real rows and independent ES readback before replaying the large workload.

## Load Routing
- Follow `AGENTS.md` first. Read this summary, `.codex/memory.md`, and task-relevant `.codex/backlog.md`, `.codex/known_issues.md`, `.codex/api_contract.md`, `.codex/architecture.md`, `.codex/decisions.md`.
- Hosted PR head, CI, Codex review and code override stale historical `pending` markers.
