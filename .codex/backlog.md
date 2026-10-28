# GenerativeLanguageModel — Active Backlog

## Current Summary

- **Latest accepted main:** `e010a5e07c45016f8f0ab4094c30bcd33825d3b5` (PR #242 user-approved merge); PR Linux `offline-e2e` #40622149444 SUCCESS, main postmerge `offline-e2e` #40623677955 **SUCCESS** (including immutable archive test), Windows 3.10/3.11 operator-deferred.
- **Already completed — do not reopen:** #240 original six-file archive compaction (6/6 review threads resolved), #241 quality-report ledger guard (1/1 resolved), #242 LLM failure-report cross-directory ledger guard (zero findings/threads). Each passed exact-head Codex and corresponding PR Linux CI before authorized merge. #239 accepted `46b7c7290417421a6dc09e114f82c1066ce0179d`; main Linux #40513712390 SUCCESS. #233–#238, #218–#230 (excluding #231), #232 and #212/#213 issue #211 resolution accepted.
- **Independent OPEN PR #231:** stopped-producer sealed JSONL rotation no-clobber rollback remains unmerged and must not be modified, rebased, closed, or merged without separate explicit user authorization.
- **This independent memory task:** archive prior active `project.md`, `memory.md`, `backlog.md` byte-for-byte under `.codex/archive/*-20261028-104900.md`, reconcile accepted/main/open state, and add a regression guard. Hosted CI and formal Codex Review for this branch pending, no Merge without user instruction.

## True Open Engineering Work

- [ ] **Independent PR #231** stopped-producer sealed JSONL rotation rollback; still OPEN/unmerged at head `a8711e9337b62e4b9c6ad62f37ba3e78ba4e8fea`. Do not modify/rebase/close/merge in this task; reassess Hosted mergeability only in separately authorized work.
- [ ] Operator real Windows/Tk GUI/PSAPI `PeakWorkingSetSize` smoke and multiple stopped-source memory-vs-SQLite benchmarks; Linux simulated Windows paths do not count as real validation.
- [ ] Operator-controlled 1–3 Windows/Ollama/ES rows with independent stored ES readback, Event ID/date precision, stage lineage, sink-acknowledged writeback before bulk production replay.
- [ ] Distinct request attempt/retry identities and reliable denominators; legacy CSV `ok` and run-scoped event catch-sites are **not** unique logical failure or affected-document denominators. Extend non-schema Producer/Worker/Stage/Row Merger attribution only with safe proof.
- [ ] Design authenticated crash-safe exact disk checkpoint/replay, generation-bound source identity and stopped/online producer safety **before** any automatic shard pruning, retirement or online rotation. Current temporary SQLite/SHA256 manifest are not substitutes.
- [ ] Explore bounded GUI restartable state/disk-backed identity with full physical restart evidence; on capacity exhaustion fail closed, never show partial totals as complete.
- [ ] Consider legacy unmarked checkpoint inventory and reduction locks only with measured need; evaluate `utils/utilities.py` active dependencies before compat-preserving refactor.
- [ ] Verify buffered ES acknowledgements/readback, while preserving queue/refresh/confirmed distinction.
- [ ] Defer #203 transient semantic cache until duplicate-call savings justify complexity; Reduction Engine v1 release is complete.
- [ ] Never treat queued Windows runners or Linux `offline-e2e` as physical Windows/Ollama/ES acceptance. Do not perform unapproved merges/deletions.

## Archived History

- `.codex/archive/backlog.md-20261027-213700.md` — exact pre-#240 original Git blob `0a40f0a9b26d7bebb7125a790995db6b84181a4f`; preserves older quality/memory backlog, decisions and historical PR status.
- `.codex/archive/backlog.md-20261028-104900.md` — exact pre-reconciliation active backlog Git blob `67b64c801806d585e246d9f0091efe4cb69d37ef`; preserves the original historical #240–#242 review/CI entries now confirmed closed.
- These archives are for historical traceability, not a current todo list. Reconcile new work against Hosted main, branch HEAD, CI and formal Reviews before marking a task completed.

## 2026-10-28 #243 closure and time-bounded observational LLM call failure counts

- [x] PR #243 user-authorized merge `5c307705884903abca882f3283ec8968b302a2d4`; formal Codex 0 Findings/Threads; main Linux `offline-e2e` #40628120579 SUCCESS including archive test. Earlier #243 in-progress notes are superseded; Windows 3.10/3.11 remains queued/operator-deferred.
- [ ] New independent `feat/llm-failure-observed-time-window-20261028`: strict opt-in local-second `--since`/`--before` filtering over existing CSV only, fail closed for unknown/malformed timestamps and rows, keep legacy v1 JSON unfiltered path unchanged; add interval/exclusion metadata only with filter; preserve bounded reader, per-run denominators, privacy. Obtain exact-head Hosted Linux E2E, Codex P1/P2 review; require explicit Merge authorization.
- [ ] Remaining independent followups: source-authoritative request UUID/retry lineage, cross-clock normalization only with explicit timezone evidence, actual logical failure denominators, real Windows/LLM/ES acceptance. PR #231 OPEN and out of scope.

## 2026-10-28 PR #244 closure and incremental record identity

- [x] PR #244 approved and squash-merged into main `9e743267676af6fc956eca3917253527797785ec`, exact-head Codex 0 Findings/Threads, PR Linux `offline-e2e` #40632361447 SUCCESS. Older checkboxes above about #244 being pending are superseded; main postmerge Linux #40660431903 initially in progress, Windows operator-deferred.
- [ ] Independent `feat/llm-audit-record-uuid-20261028`: per-emitted-CSV-row UUID4 in new runs, old current-schema header preservation, unknown legacy header fail closed, CSV/XLSX + offline report tests, exact-head Linux and formal Codex re-review. Do not merge without user permission. Keep #231 OPEN and untouched.
- [ ] **Further separate work**: true provider request/retry-family/dispatch IDs supplied at worker call start (can persist across retry attempts), cross-layer failure attribution and accurate logical denominators. Do not infer these from audit-row UUIDs, timestamps or repeated prompt paths. Physical Windows/Ollama/ES readback still required.

## 2026-10-28 PR #245 accepted; Worker call identity phase

- [x] PR #245 user-approved squash merge `bc0a46ababa40f67004659a0b15dd0b29cd31303` (official exact-head zero Findings/Threads, PR Linux `offline-e2e` #40661652119 SUCCESS). Previous #245 pending checkbox is historical. Latest main postmerge #40663629016 initially running, Windows operator-deferred.
- [ ] Independent `feat/llm-worker-call-id-20261028`: mint `worker_call_id` *at actual CallLLMAPI boundary* and record alongside separately minted `audit_record_id`. Preserve prior two CSV generations; retain v1 summary, privacy and per-run cardinality. Complete exact-head Hosted Linux E2E, formal Codex review, evidence; no Merge without user authorization. PR #231 OPEN untouched.
- [ ] Future separate source-authoritative logical retry grouping across Worker resubmissions, exact provider HTTP attempt visibility if SDK exposes it, missed audit/crash evidence and durable dispatch checkpointing. Do not compute logical retries or document failure rates from `worker_call_id`, `audit_record_id`, CSV `ok`, or prompt filenames. Real Windows/Ollama/ES readback remains operator-gated.

## 2026-10-28 #246 accepted; wrapper-return boundary follow-up

- [x] PR #246 user-approved squash merge `0b380ae65d9bc0b388b66bfa8a6c216ca8e0782d` (official exact-head 0 Findings/Threads, PR Linux `offline-e2e` #40665096448 SUCCESS). Historical checkbox about #246 pending is superseded. Main postmerge #40671779239 initially in progress; Windows operator-deferred.
- [ ] Independent `feat/llm-worker-call-return-outcome-20261028`: record strict explicit YES/NO/unknown `CallLLMAPI` wrapper return boundary per Worker ID, distinct from `ok` and `audit_record_id`, with new audit field plus three-generation legacy header-safe append and tests. Exact-head Hosted Linux + official Codex Review required; no Merge without user authorization. PR #231 untouched.
- [ ] Future logical retry families must originate in authoritative dispatch/resubmission state, not raw prompt filenames, Worker call UUIDs or `CallLLMAPI` wrapper-return telemetry. Internal SDK HTTP attempt counts and actual provider root cause need distinct source evidence; Windows/Ollama/ES end-to-end and independent sink readback remain operator-gated.

## 2026-10-29 #247 accepted; split-intent retry family provenance

- [x] PR #247 user-approved squash merge `d61d223f80ff7f12c9a04ba8f002e8be26d71a5c`; official exact-head review zero Findings/Threads; PR Linux `offline-e2e` #40673229040 SUCCESS incl. immutable archives. Previous #247 pending notes superseded. Main postmerge #40715931308 initially queued; verify independently.
- [ ] Independent `feat/verified-split-retry-lineage-20261029`: add optional opaque UUID4 to **persisted explicit JSON split-intent** v1 journal, inherit only through SHA256-verified direct child lineage including nested splitting, legacy unknown, no inferred generic retries, no CSV/report schema change. Obtain Hosted exact-head Linux `offline-e2e` + official Codex review; Merge only on explicit user authorization. #231 OPEN untouched.
- [ ] Separate future branch: correlate actual Worker calls with verified split-intent families without trusting prompt paths or assuming provider HTTP retries; specify source snapshot and crash/restart constraints first. Genuine repeated identical Worker's RUNNING→TODO attempts, SDK internal retries and unique-document denominators still have no authoritative lineage. Do not auto-compute retry success rates from split IDs.

- [ ] PR #248 four P2 first-review findings: nested A→B lineage conflict, identity-directory symlink aliasing, deep-nested JSON RecursionError, and noncanonical/non-v4 UUID placeholders. New candidate fixes plus regression tests committed; require *new exact HEAD* Hosted Linux and official review, close/resolve only after independent verification. Keep #231 untouched and do not Merge without permission.
