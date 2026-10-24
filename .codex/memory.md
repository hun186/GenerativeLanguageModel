# Project Memory

## Current Summary

- GenerativeLanguageModel processes TXT, Table, SQLite, SQL Server, ES, local LLM/Ollama, multistage extraction, reduction and guarded writeback. Reduction Engine v1 release is complete; keep source/dispatch identity and ES strict event-schema constraints fail-closed.
- **Latest Hosted main:** `e9a7e549205323b310ba7063cde5e39b0f5e1e01` (#225 merged). Exact-head Codex 0 Findings, all review threads resolved, PR Linux offline-e2e succeeded; post-merge main run #39984570836 Linux offline-e2e SUCCESS. Windows self-hosted runners remain operator-deferred.
- User authorization is required for every merge. No claim of real Windows/Ollama/SQL Server/ES end-to-end writeback acceptance from Linux offline CI. Next operator gate: 1–3 controlled rows with independent ES readback.
- #213 SQLite/Excel extract E2E and durable raw-source/dispatch provenance, #214/#215 strict multidimensional ES merge/terminal references, #216 article-date/importance score shape, #218–#221 quality observation/offline report, #222 Consumer incidents, #223 Row Merger retries, #224 Producer incidents, #225 Stage orchestration events are merged. Historical exact commits and findings: see archived snapshot.
- Quality events are strictly code/event/scope matched, run-scoped orchestration events cannot have document or slice identities, audit writes are best effort. Quality event counts are neither failed document counts nor LLM request failure rates. Old CSV audit records may contain raw errors and require controlled access.
- Windows self-hosted smoke, provider/ES durable acceptance, cache item #203, streaming quality JSONL lifecycle and deeper Worker crash/root-cause coverage are not completed.

## Current Focus — PR #226 (independent, awaiting Hosted acceptance)

- Branch: `feat/quality-worker-execution-phases-20261024`. At the actual `PromptAPIPipeline.proc()` leaf Worker caught-exception boundary, distinguish `WORKER_PRECALL_EXCEPTION`, `WORKER_LLM_CALL_EXCEPTION`, `WORKER_RESPONSE_EXCEPTION` and `WORKER_PERSIST_EXCEPTION` from control-flow execution site, never parse raw exception text.
- New `worker_phase_failure` / scope=run JSONL event carries no stage/chunk/document/slice identity, prompt, output, URL, secrets, file path or raw exception. Independent `worker_phase_failure_events` counter and GUI label preserve original document/slice denominators.
- Real `PromptAPIPipeline.proc()` branch-specific regression tests cover four phases, successful call, mock-only exception, cooperative cancellation, request-CSV behavior, output secrecy and writer failure. Hosted Linux CI includes Worker focused tests; no local/Windows/live provider verification claimed.
- **Status:** Code/tests/docs committed on #226 branch; wait for exact-head Hosted Linux offline-e2e, formal Codex review and remediation (if any). Do not merge without user's explicit instruction.
- Interpret `WORKER_LLM_CALL_EXCEPTION` as failure raised by `CallLLMAPI()` invocation (could be local/client/transport/provider), never automatically as a proven remote model outage. Consumer/Producer/Stage/Worker events can overlap the same logical failure.

## Recent Outcomes

- 2026-10-23 #222–#225 merged after exact-head Linux CI and Codex. #224 fixed schedule/bookkeeping taxonomy P2 and cancellation-cleanup P2; #225 Stage Runner and preparation observation uses two-argument compatibility fallback and excludes cooperative cancellation.
- 2026-10-24 #225 post-merge main Linux offline E2E verified SUCCESS. Independent leaf Worker execution-phase branch prepared with Quality schema, GUI, docs, strict privacy and tests. Windows/live acceptance still deferred.
- 2026-10-24 memory compaction: full active memory and known issues were archived **before** rewriting; all past findings, prior PR review/CI evidence, outstanding history and links remain in the snapshots below.

## Archived History

- `.codex/archive/memory.md-20261024-before-pr226-review.md`: exact full 33,726-character active memory snapshot through PR #225 and #226 branch implementation. Earlier historical review/correction/CI details preserved.
- `.codex/archive/known_issues.md-20261024-before-pr226-review.md`: complete active known issues through Stage and Worker quality work; contains earlier unsolved operational caveats.
- `.codex/archive/memory.md-20261019-before-pr216.md`: earlier full historical memory through PR #215, referenced by the above snapshot.
- Pending statuses in archived snapshots reflect their historical recording dates, not the current Hosted PR status.

## 2026-10-24 PR #226 closure and next typed-SDK observability branch

- PR #226 leaf Worker execution-phase quality telemetry passed exact-head formal Codex (0 Findings, 0 unresolved threads) and PR Linux offline-e2e. With explicit user permission, merged as `a4eb5ec3fcb68eb07ae849f77294cc8b72a59b24`. Post-merge `main` run #40066964887 `offline-e2e` SUCCESS. Windows self-hosted and live Ollama/ES remain operator-deferred. The older #226 "awaiting Hosted" passage above is historical.
- New independent branch `feat/quality-llm-sdk-error-codes-20261024`: preserve `CallLLMAPI` output/exception behavior and leaf Worker's single run-scoped `worker_phase_failure` event per caught exception; refine only the `WORKER_LLM_CALL_EXCEPTION` phase using *typed OpenAI SDK evidence*. Codes: `WORKER_LLM_TIMEOUT_EXCEPTION`, `WORKER_LLM_CONNECTION_EXCEPTION`, `WORKER_LLM_RATE_LIMIT_EXCEPTION`, `WORKER_LLM_HTTP_SERVER_EXCEPTION` (5xx), `WORKER_LLM_HTTP_CLIENT_EXCEPTION` (4xx), and `WORKER_LLM_RESPONSE_VALIDATION_EXCEPTION`. Unrecognized call-site exceptions remain `WORKER_LLM_CALL_EXCEPTION`.
- Preserve legacy timeout/connection `RuntimeError` wrappers and use only a typed direct SDK `__cause__` for attribution, not exception strings, URLs, tokens or raw payloads. These fixed codes identify SDK failure mechanisms, not proof that a remote model is responsible. Server 5xx is an observed HTTP response; client 4xx may be credential/configuration/request errors. SDK default retries may cause multiple HTTP attempts, but the Worker incident remains one caught exception.
- Added SDK typed-contract tests, a fully in-memory httpx.MockTransport invocation of actual `CallLLMAPI`, Worker-to-JSONL single-event / CSV regressions, parser privacy/denominator tests, and fallback when classification itself throws. Hosted Linux offline-e2e includes these focused tests.
- **Status: committed work on separate unmerged branch; exact-head Hosted Linux CI and formal Codex P1/P2 acceptance must be checked, with explicit user permission required before merge.** No real Windows/LLM/ES acceptance claim.


## 2026-10-24 PR #227 closure; scoped run-only incident drilldown PR

- PR #227 `feat/quality-llm-sdk-error-codes-20261024` passed latest-head Codex with 0 Findings / 0 unresolved threads and Linux offline-e2e #40069591703 SUCCESS. Explicit user-authorized merge `45a6b6e663f1bbe1ad30eccd403f593b0860de1c` now main. The earlier “pending #227” block is historical. Post-merge main Linux offline-e2e #40070824184 was **still in progress** when the next branch was started; do not promote it to passed without live Hosted evidence.
- New independent `feat/quality-run-incident-drilldown-20261024`: add read-only `incident_diagnostics` to existing offline single-run/history JSON report and CLI `--incident-family`, backed solely by strict `QualityTailReader` accepted `error_codes`. Run-only family allowlists derive directly from existing `_EVENT_CODES`/`_EVENT_SCOPES`. Worker typed SDK codes from #227 require no new classifier table.
- Include per-run `observed_run_incident_events`, per-family accepted counts, nonzero bounded `codes`, observed incident composition shares (null when denominator zero), and n<30 advisory. Focus only narrows the visible family breakdown; always retain full raw `metrics` and denominator of *all* run-only incidents. These counts are **not** unique logical failures, failed HTTP requests, affected documents, slices or persisted ES results; catch sites can overlap.
- No raw event payloads, document IDs, URLs, credential material or exception text in new drilldown fields. No new writers, LLM calls, DB/ES actions, GUI changes, or JSONL replay; strict parser flags invalid identity/unknown record with degraded completeness. New focused mocked JSONL regression tests and Hosted Linux offline-e2e wiring.
- **Status:** code/tests/docs committed on separate unmerged branch. Require exact-head Hosted offline-e2e and formal Codex P1/P2 review with zero unresolved threads, followed by explicit user authorization for merge. Windows self-hosted and real Ollama/ES writeback/readback remain operator-deferred.
