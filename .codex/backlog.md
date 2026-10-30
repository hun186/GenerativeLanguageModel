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

## 2026-10-29 next Worker-to-split-family evidence

- [x] #248 accepted squash merge `8468ed5bc8382c62d6f7278be60264f84e57db7f`, prior Linux #40738436235 SUCCESS and Codex 0 Findings/Threads. Historical #248 pending entries superseded.
- [ ] Independent `feat/worker-split-family-audit-20261029`: source-verified Worker call correlated to existing persisted explicit split intent via new trailing CSV/XLSX `split_family_id`; tests on real queued/journal files, actual Worker proc with isolated model, failure-report-v1 and legacy-width regressions. Await exact-head Hosted Linux, immutable archive and formal Codex Review. Do not Merge without user authorization; PR #231 unchanged.
- [ ] Later: generation-locked authenticated crash/replay, generic resubmission and SDK HTTP attribution, unique-document denominators and controlled Windows/Ollama/ES persisted readback.

## 2026-10-29 #231 reconciliation work

- [ ] #231 old head `a8711e9` was safe only on obsolete base; reconcile onto current `main` `d7d385a` without losing accepted #249/GUI/archive changes. New dedicated recovery regression in hosted Linux `offline-e2e`; validate actual successful exact-head CI and fresh formal Codex review. User Merge approval required.
- [ ] Stop producers/GUI before any real restoration; actual Windows hardlink/locking behavior, malicious filesystem interference and physical service acceptance remain operator-deferred. Never claim automated crash recovery or authenticated history.

## 2026-10-29 queue observation work

- [ ] Queue event phase 1: real claimed/requeued rename observations and strict privacy-minimal read-only counts, actual filesystem tests, Hosted Linux E2E/immutable archives and formal exact-head Codex Review; do not merge without user instruction.
- [ ] Phase 2: source-generation-verified requeue-to-next-claim linkage plus observed Worker call binding. Cover stage-managed and direct split paths, crashes, inode reuse/unchanged bytes, cross-process writer locks; do not infer a retry family from file path, prompt hash, event timestamp or `worker_call_id` alone. Real SDK HTTP retries and ES/SQL writeback denominators remain separate.

## 2026-10-29 phase 2a claim/Worker source correspondence

- [ ] New PR: optional actual-claim receipt pass-through to streaming Worker + verified `queue_claim_event_id` in newly emitted CSV/XLSX and exact five legacy-header widths. Actual queue filesystem and isolated LLM-call tests; latest-head Hosted Linux `offline-e2e` and immutable archive check; formal Codex Review; Merge requires user approval.
- [ ] Future: link real requeue and subsequent claim to source generations through authoritative persisted state, including stage-managed paths, missing events/crashes, immutable generations and concurrency; distinguish claim attempts, Worker invocations, SDK HTTP retries, JSON split families and acknowledged downstream sinks. Never infer from filename/SHA256 matches or report as unique logical retry success rates.

- [ ] **Separate queue scheduling correctness issue:** legacy recursive TODO collection flattens nested names into RUNNING basename, and os.replace may overwrite an earlier claimed file with a duplicate basename. Provide collision-safe queue claim behavior, preserved stage paths or explicit no-overwrite and migration/recovery tests; do not silently alter it inside #252 audit attribution. This phase suppresses ambiguous claim IDs only.

## 2026-10-29 claim collision prevention phase 2b

- [ ] New PR: make TODO→RUNNING fail closed for duplicate nested basenames, existing RUNNING target, symlink/hardlink/unsupported FS; exclusive hardlink no-overwrite + source unlink, preserving tuple and evidence semantics; real-file concurrent/collision/interruption tests, exact latest Hosted Linux E2E/archive and formal Codex Review; user authorization required before Merge.
- [ ] Separate no-clobber review of RUNNING→TODO recovery/timeout and RUNNING→Success destinations (potential overwrite or stale source). Define operator recovery workflow for interrupted hardlink+unlink window, pending duplicate names, unsupported filesystem; evaluate queue liveness and diagnostics.
- [ ] Later: durable source-generation/lease based logical Retry Family across retries; Worker UUID/Claim UUID are per-attempt and split family remains JSON-only, never derive denominator from repeated basename/hash.

## 2026-10-30 — operator-gated credential-history cleanup
- [ ] Have operator revoke potentially exposed provider keys/active SQL logins and preserve source-IP/account audit evidence securely.
- [ ] Run exact-head Hosted read-only preflight and formal Codex review; record branch/ref SHA snapshot and check delta against #256 evidence.
- [ ] Independently inspect >2MB blobs, forks, PR refs, GitHub Actions logs/assets, other public repo histories, compiled Python and false positives without public secret values.
- [ ] With separate approval, perform private mirror backup and restore, isolated git-filter-repo rehearsal, confidential SQL literal replacement, full-ref scan and #254 migration validation. Never rewrite public Git or force push without a new explicitly approved execution packet.

## 2026-10-30 — production credential security follow-up
- [ ] Verify exact-head Hosted credential synthetic tests, changed-line scanner, offline Linux E2E, formal Codex review and review-thread resolution for the new PR; merge only on user approval.
- [ ] Operator deploy: inject `CZJLLM_ES_HOST`/`CZJLLM_ES_USERNAME`/`CZJLLM_ES_PASSWORD` and SQL variables via OS secret manager or private `.env.production`, check staging login and TLS hostname/SAN, then confirm production behavior without displaying secret values.
- [ ] Revoke/rotate any **still-valid** Elasticsearch credentials previously committed and independently verify old SQL logins; do not confuse DeepSeek revocation with other service credentials.
- [ ] Long term: consider separate ES profiles for independent clusters and remove hostname-verification bypass where correct certificates are available; maintain no plaintext runtime secrets in tracked examples. Historical ref cleanup remains deferred and explicitly approval-gated.

## 2026-10-30 — preferred private connection-profile deployment
- [ ] Exact-head GitHub CI, private-profile regressions, secret scan, Linux E2E, formal Codex re-review and resolution of new findings required for PR #258; user approval needed for Merge.
- [ ] Operator must create or migrate real SQL/ES full connection files to ignored `config_sql/private/` and `config_es/private/` before deployment; verify path selection and live connectivity without exposing values. Back up these private folders securely and exclude from deployments/releases shared with others.
- [ ] Rotate any still-live SQL/ES credentials that had previously appeared publicly. DeepSeek key revocation alone does not imply rotation of database credentials; full Git-history rewrite remains separately deferred.

## 2026-10-30 — connection profile untracking deployment gate
- [ ] Run exact-head Hosted security regression (including 11 root file absence/11 public template assertions), changed-lines secret scan, Linux E2E and formal Codex Review on PR #258; 0 outstanding P1/P2 before requesting Merge.
- [ ] Before deployment, operator locally copies complete SQL/ES root profiles to the ignored `private/` directories (optionally with `scripts/migrate_connection_profiles_to_private.py --apply` on a checkout where originals still exist), confirms SHA/contents privately, then validates old YAML path resolution and actual connection. Never assume GitHub could migrate local secrets.

## 2026-10-30 — after accepted PR #258

- [x] PR #258 user-approved Squash Merge `a2815b369e80108fbc893d3d8b97e4f29f20e878`: remove 11 tracked SQL/ES root connection files, retain 11 sanitized templates and private path compatibility; exact-head formal review clean, Linux offline-e2e and secret scan passed. Historical earlier [ ] items for #258 in this document are superseded.
- [ ] Current new branch `security/private-profile-deploy-preflight-20261030`: run exact-head Hosted no-network private-profile safety tests, secret scan, Linux offline E2E and formal Codex Review; resolve all findings, then request user authorization before merging.
- [ ] Operator only: after updating local checkout, restore backed-up complete `config_sql/private/` and `config_es/private/` files, run read-only preflight, validate real SQL/ES logins and ES TLS certificates. Never print or upload credentials; no GitHub action can validate local private files.
- [ ] Independently determine whether previously public SQL/ES credentials remain valid and rotate if needed. Do not do public Git history rewrite, branch deletion, force push, or #254 edits without separate authorization.

## 2026-10-30 — ES anonymous development preflight follow-up

- [x] PR #259 previously user-approved Squash Merge to main SHA `8fca421c772430493bf5e49f3cd8cf946973f218`; read-only SQL/ES static preflight landed with Hosted synthetic unit/secret scanner and Linux E2E PASS. Windows live private profile check and actual SQL/ES authentication remain operator-only.
- [ ] New independent security PR: allow explicit nonproduction single-file anonymous Elasticsearch static inspection without weakening default auth requirements, production checks or field/path/Git hygiene. Require latest-head Hosted synthetic tests, changed-line scan, Linux E2E, formal Codex review and explicit owner merge authorization.
- [ ] Operator confirm ES PROFILE_4 corresponds to an intentionally anonymous development endpoint. If credentials are actually required, repair private file locally instead; never commit real secrets. Runtime ES/TLS authentication and SQL still require operator validation.

## 2026-10-29 phase 2c recovery and Worker Success protection

- [ ] New PR: no-clobber RUNNING→TODO recovery/timeout and direct Worker Success publication with conflict preservation, source/receipt semantics and actual-file concurrency tests, exact-HEAD Hosted Linux CI and formal Codex Review. User Merge permission required.
- [ ] Audit stage-managed and alternate Success writers, explicit full-restart policies, collision recovery tooling and prior Success provenance; no automatic manual artifact deletion or reinterpretation of stale results. Require Windows filesystem and actual LLM/ES/SQL operator E2E before claims of deployment readiness.
- [ ] Durable source generations and trusted cross-claim logical Retry Family remain deferred; distinct from one claim UUID, Worker invocation UUID, split-intent UUID and SDK internal HTTP requests.

- [ ] **2026-10-30 current PR #254 integration:** original phase 2c review was clean on its prior HEAD but branch was unmergeable after later security merges. Main-first two-parent integration on latest main preserves security patches and original queue fixes; fresh exact-head Linux E2E/Codex Review required, then explicit owner Merge approval.

## 2026-10-30 — after accepted #254, phase 2d queue recovery inventory

- [x] PR #254 user-approved Squash Merge `9af997458bb8267735a4cd1fe793263eb0a8d2b0`: no-clobber RUNNING→TODO and Worker Success publication; prior historical #254 [ ] pending review rows superseded. Linux E2E + exact-head Codex review pass; Windows/SMB and live services not verified.
- [ ] New PR phase 2d: ship read-only, secret-free and non-atomic operator inventory of orphan Success staging, interrupted hardlink move candidates, duplicate TODO names and collisions. Run exact-head Hosted synthetic tests, Linux E2E, formal Codex Review, resolve Findings; Merge only after explicit authorization.
- [ ] Future separate scope: operator-approved, generation-verified recovery workflow (no automatic unlink), cross-process crash/restart/SMB behavior, all alternate Success writers; no trusted general Retry Family or committed ES/SQL sink truth yet.

- [ ] **Phase 2d formal Codex P2 remediation on PR #261:** run new exact-head Hosted Linux E2E & second formal Codex Review after four initial P2s (Windows zero identities, path scandir redirect race, unbounded sorting, junctions). New code uses anchored POSIX handles, streaming entry budget, unknown ID fail-closed, Windows unsupported gate; 20 synthetic tests. Do not Merge without owner approval.
- [ ] **Separate Windows-native secure recovery diagnostics:** implement Windows handle-based no-reparse directory traversal and reliable FILE_ID_INFO/link counts with genuine Windows self-hosted filesystem tests; current phase 2d intentionally refuses Windows rather than risk silent external/junction traversal. Real SMB and service recovery remain operator-deferred.

- [ ] **PR #261 second-round Codex P2s:** reject unchecked `..` before normalizing item paths, correct three mock tests' capability gate and Windows unsupported-platform skips; add symlink/nonexistent/relative parent traversal regressions. Re-run exact-HEAD Hosted Linux E2E plus secret scan and third formal Codex Review, resolve findings, request explicit owner Merge approval. Prior head `925b5ec32f` had 3 new P2 and FAILED Linux E2E; never count as acceptance.
