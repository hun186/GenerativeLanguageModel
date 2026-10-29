# GenerativeLanguageModel — Active Project Router

## Current Focus

- **Current 2026-10-29:** #248 user-approved merged to main `8468ed5bc8382c62d6f7278be60264f84e57db7f` (prior exact-head Codex zero Findings/Threads and Linux #40738436235 SUCCESS). New `feat/worker-split-family-audit-20261029` links source-matched real Worker calls to verified persisted split-intent family UUIDs. It captures parents after the repair journal is written, descendants via direct/nested evidence, and emits an optional trailing CSV/XLSX field while preserving four prior headers and unchanged failure report-v1. Main postmerge #40790298292 initially queued; real Windows/Ollama/ES deferred. PR #231 OPEN/untouched; new branch Linux and Codex review still pending, NO Merge authorized.


- **Authoritative main 2026-10-28:** user-approved #247 squash-merged at `d61d223f80ff7f12c9a04ba8f002e8be26d71a5c`; exact-head formal Codex Review 0 Findings/Threads and PR Linux `offline-e2e` #40673229040 SUCCESS incl. immutable archives. Main postmerge #40715931308 needs explicit completion check; Windows 3.10/3.11 operator-deferred. Older #247 pending/current-focus entries below are superseded. Independent PR #231 OPEN/untouched.
- **Current bounded engineering branch:** `feat/verified-split-retry-lineage-20261029` enriches existing v1 persisted single-extract JSON split-intent journal with random `split_family_id` UUID4 and adds a digest-verified direct parent/child/nested lineage lookup. Old journals remain readable as **unknown**, not retroactively attributed. This is only explicit split-intent ancestry, not general RUNNING→TODO, provider/SDK retries, document/HTTP identity, completed split or authoritative failure denominator. No LLM, ES/SQL, CSV/XLSX or report schema changes. Require latest-head Hosted Linux CI and formal Codex review; do not Merge without user permission.

- **Latest accepted Hosted main (2026-10-28):** user-approved #246 squash merged as `0b380ae65d9bc0b388b66bfa8a6c216ca8e0782d`; formal exact-head Codex 0 Findings/Threads and PR Linux `offline-e2e` #40665096448 SUCCESS incl. archive test. New main postmerge #40671779239 initially running; Windows 3.10/3.11 operator-deferred. Older #246 pending labels below are historical/superseded; independent PR #231 stays OPEN untouched.
- **Next independent engineering branch:** `feat/llm-worker-call-return-outcome-20261028` records explicit `CallLLMAPI` wrapper normal return as `call_llm_api_returned` YES/NO (unknown blank outside observed Worker boundary), separate from the final local `ok` result. It preserves three historical CSV header generations, report-v1 semantics and privacy. This is **not** a provider HTTP acknowledgement or retry lineage. Require exact-head Hosted Linux CI, formal Codex Review and explicit Merge approval.

- **Authoritative 2026-10-28 accepted main:** user-approved #245 squash-merged as `bc0a46ababa40f67004659a0b15dd0b29cd31303`; formal exact-head review 0 Findings/Threads; PR Linux `offline-e2e` #40661652119 SUCCESS (immutable archives included). New main postmerge #40663629016 Linux initially running; Windows self-hosted queued/operator-deferred. Older #245-in-progress entries below are historical/superseded.
- **Independent current engineering branch:** `feat/llm-worker-call-id-20261028` adds Worker invocation-bound UUID4 `worker_call_id` minted only immediately before real `CallLLMAPI`, separate from the persisted audit row UUID; CSV/XLSX newest header carries it, old two generations stay width-compatible. **Not** HTTP/provider request UUID or logical retry-family lineage. Requires Hosted Linux CI, exact-head Codex Review and explicit user Merge. Independent PR #231 remains OPEN untouched.

- **2026-10-28 newest main:** user-approved PR #244 merged with squash SHA `9e743267676af6fc956eca3917253527797785ec`; exact-head Codex 0 Findings/Threads, PR Linux `offline-e2e` #40632361447 SUCCESS. Main postmerge #40660431903 Linux still in progress at initial check; Windows 3.10/3.11 queued/operator-deferred. The previous #244-in-progress focus below is historical and superseded.
- **Current independent work:** `feat/llm-audit-record-uuid-20261028` adds opaque `audit_record_id` UUID4 to *new* per-run LLM CSV/XLSX audit rows; exact legacy immediately prior header continues without new column, unfamiliar existing header fails closed. This is persisted audit-row identity, **not** a provider request UUID, logical retry identifier or document-failure denominator. Requires exact-head Hosted Linux CI, formal Codex Review, explicit Merge authorization. PR #231 stays OPEN/untouched.

- **Verified GitHub 2026-10-28:** PR #243 user-authorized merged to `main` SHA `5c307705884903abca882f3283ec8968b302a2d4`; formal exact-head Codex 0 Findings, 0 unresolved Threads; postmerge Hosted Linux `offline-e2e` #40628120579 SUCCESS including immutable archive regression. Earlier #243 branch-as-current and "review pending" entries below are historical/superseded. Windows self-hosted 3.10/3.11 queued/operator-deferred; independent PR #231 OPEN, untouched.
- **Current independent engineering focus:** `feat/llm-failure-observed-time-window-20261028` adds opt-in strict `--since` inclusive / `--before` exclusive producer-local naive timestamp filtering to read-only `llm_failure_report`, retaining legacy unfiltered report-v1 shape and source snapshot bounds. Missing/malformed timestamps fail closed; no retry UUID inference, no unique-document denominator. Require new exact-head Linux CI and formal Codex Review. **No merge without explicit user instruction.**


- **Authoritative accepted main (2026-10-28):** user-approved PR #242 merged as `e010a5e07c45016f8f0ab4094c30bcd33825d3b5` after formal exact-head Codex Review (0 Findings, 0 unresolved Threads) and PR Linux `offline-e2e` #40622149444 SUCCESS. Main postmerge Linux `offline-e2e` #40623677955 **SUCCESS** including immutable archive test, as checked on Hosted GitHub. This is Linux-only evidence, not full Windows or ES/Ollama acceptance. Windows self-hosted 3.10/3.11 remain queued and **operator-deferred**.
- **Current independent memory-reconciliation branch:** `docs/codex-current-handoff-reconciliation-20261028` archives full prior active `project.md`, `memory.md` and `backlog.md` byte-for-byte **before** replacing obsolete current-focus claims; verifies archive Git blob SHA in Hosted Linux and preserves all original six 2026-10-27 immutable archives. No runtime code changes, formal latest-head CI/Codex review and explicit user Merge authorization still required.
- **Only independent outstanding PR at this baseline:** #231, OPEN/unmerged, head `a8711e9337b62e4b9c6ad62f37ba3e78ba4e8fea`. Its interrupted sealed-JSONL rotation rollback remains separate: do not edit, close, rebase or merge it without a separately authorized workflow. Mergeability must be rechecked rather than trusted from old snapshots.

## Recent Accepted Outcomes

- **#242** cross-directory `llm_failure_report --output` SHA256-ledger protection merged `e010a5e07c45016f8f0ab4094c30bcd33825d3b5`; Codex exact-head zero Findings/Threads and PR Linux #40622149444 SUCCESS.
- **#241** offline `processing_quality_report --output` ledger protection merged `fb713365b173378ba8ca82e0557e4fdd5a415650`; Codex zero Findings, 1/1 Thread resolved, PR Linux #40609259343 and main Linux #40616682036 SUCCESS.
- **#240** archive-first six-file active-memory compaction merged `21ae2cb690031c6409fd05f5cf6e4109a21548e1`; Codex zero Findings and 6/6 Threads resolved; PR Linux #40530750923 and main Linux #40604470304 SUCCESS. Preserve its six immutable Git blobs and retained ES/resume/cache audit contracts.
- **#239** finite benchmark numeric validation merged `46b7c7290417421a6dc09e114f82c1066ce0179d`; postmerge Linux `offline-e2e` #40513712390 SUCCESS.
- #233–#238 are accepted: GUI over-cap replay guard, exact temporary SQLite spill, subprocess resource/working-set/parent-wall benchmark safety. Earlier quality/GUI/manifest #218–#230 (except #231) and #232 accepted. Issue #211 corrected by #212/#213; Reduction Engine v1 release complete. #203 optional transient cache deliberately deferred.

## Open Handoffs

- **Operator-gated:** real Windows/Tk + PSAPI benchmarks, 1–3 controlled Ollama/ES writebacks with independent persisted readback and stage/Event ID/date checks. Neither queued Windows jobs nor Linux E2E prove this acceptance.
- **Engineering:** resolve #231 only in its own authorized branch; evaluate authenticated crash-safe checkpoint/replay, safe online rotation/retirement, GUI restartable bounded state, and source-authoritative retry denominators/error taxonomy. Existing temporary SQLite, SHA256 manifest and catch-site events do not establish those properties.
- **Safety:** no automatic pruning/deletion or unauthorized Merge. A previous dated `[ ]` entry is not current merely because it appears in historical archives. Verify latest Hosted GitHub state before proceeding.

## Load Routing

- Read root `AGENTS.md`, then `.codex/project.md` and task-relevant active `.codex/{memory,architecture,api_contract,known_issues,decisions,backlog}.md`. Open older archives only for specific traceability.
- Hosted HEAD/CI, production code and official Codex Reviews override historical `pending` notes. When a PR merges, reconcile **Current Focus** before the next independent task.

## Archived History

- `.codex/archive/project.md-20261028-104900.md` — exact pre-reconciliation active router Git blob `a4eeb14fe91dadbb3583087a1517f1f290f2834c`; retains prior HEADs, completed review chronology and superseded `pending` labels. This archive is historical, not a current work queue.
- Original six `.codex/archive/*.md-20261027-213700.md` snapshots remain untouched.
