# GenerativeLanguageModel — Active Backlog

## Current Summary
- **Accepted baseline:** main `e010a5e07c45016f8f0ab4094c30bcd33825d3b5`, Linux offline-e2e #40623677955 **SUCCESS**; PR #239 commit `46b7c7290417421a6dc09e114f82c1066ce0179d`, #40513712390 **SUCCESS**; #231 remains independent OPEN. PR #240, #241, #242 already accepted/merged, never reopen. Windows selfhosted / operator real NTFS/SMB remains **operator-deferred**.
- **Latest accepted queue main:** #267 handoff `923d7b8d810aa243f4238c9efb3a9748a5e4579a`; #268 exclusive RUNNING no-clobber `ed131529e8c012cd7779d336832efda941b2f001` merged. Other historical #243–#265 outcomes and earlier findings archived verbatim; consult archives only when needed.
- **Current active high-risk PR #269:** `fix/strict-restart-recovery-20261031` OPEN. Safe strict enumeration, bounded retry, per-item quarantine, finite deferred recheck, healthy-row continuation and queue-integrity meter; external verified pending marker MUST reconcile RUNNING→TODO receipts once per consumer and never be mistaken for job Success. Production Windows/SMB approval not established.
- **Current GUI work in #269:** shared Windows `win_gui.py` button `重大異常檢閱／管理`; per-run meter and optional explicit old item path; operator actions `resolved/ignored/deleted(open-hidden tombstone)/open` recorded in `queue_review_actions.jsonl`. This never deletes queue sources, authoritative recovery marker, or SQL/ES. Headless GUI/API tests are CI-gated. Polling must continue after every successful/failed refresh.
- **Owner merge gate:** full_restart / sink integrity is high risk; require latest exact HEAD Linux E2E, Windows Hosted 3.10 and 3.11, changed-line secret scan, formal Codex Review CLEAN with zero unresolved P1/P2 Threads, branch rules and **explicit owner Merge permission**; never automatically merge.

## True Open Engineering Work
- [ ] Complete PR #269 newest-head Hosted Linux offline E2E, Windows 3.10/3.11 NTFS, secret scan, formal Codex re-review and remediate findings. No Merge pending explicit owner approval.
- [ ] **Issue #266:** real operator Windows/SMB/NTFS, live Ollama, SQL/ES sink-ack/readback and Tk GUI interaction acceptance. Hosted CI is not physical operator acceptance; no unverified Windows auto-replay.
- [ ] **Separate PR #231** sealed JSONL rotation no-clobber rollback remains OPEN; do not modify, close, merge or rebase without separate authorization.
- [ ] Native production writer-quiescence/stop evidence, authenticated replay identity and generation-bound checkpoint before any auto source rebuild or queue cleanup; never assume a stale RUNNING worker is safe to replay.
- [ ] Add central all-project incident inventory only if user requests beyond current-run structured queue recovery/writeback codes; preserve privacy and per-run scopes. Optional owner-directed notification, not a silently installed service.
- [ ] Durable error stream for non-schema Producer/Worker/Stage/Row-Merger failures, authoritative request/retry lineage and correct denominator; do not infer document failure from audit rows or cached tokens.
- [ ] Verify GUI/Tk/PSAPI PeakWorkingSetSize, partial metric reporting and restart-capacity behavior on actual Windows; never mark partial results complete.
- [ ] Audit ES event_ids/date-precision/stage lineage with independently confirmed sink readback; preserve source, repaired and acknowledged distinction.
- [ ] Evaluate crash-safe checkpoint/identity, bounded reduction disk state, GUI observability and cache only after demonstrated need. Never change sensitive config or unsafe API keys.

## Recent Changes
- 2026-10-28 to 2026-10-31: #243–#265 concluded in historical archived handoffs; staged Windows native safe-handle probes, queue no-clobber, identity and queue-inspector work. Operator Windows acceptance #266 still pending.
- 2026-10-31: #268 merged. #269 staged strict restart, three-attempt retry, per-item blocked/incomplete, five 30s cooldown rechecks, persisted operator escalation and metadata-only supervisor CLI.
- 2026-11-01: #269 GUI management and review-only audit ledger; hard safety veto on marking active blocked/writeback failures as resolved; fixed missing GUI polling callback and duplicate recovered-item adoption. **All still pending final acceptance.**
- 2026-11-01: **Archive-first compaction**: preserved the complete 205-line prior active backlog verbatim in `.codex/archive/backlog.md-20261101-124200.md` before reducing this active summary to within 200 lines / 40 KB. Retain all old open handoffs and review traces in immutable archive.

## Archived History
- `.codex/archive/backlog.md-20261101-124200.md` — full original #269 development chronology, old active backlog immediately before latest compaction.
- `.codex/archive/backlog.md-20261028-104900.md` — original Git blob `67b64c801806d585e246d9f0091efe4cb69d37ef`; pre-reconciliation work preserved byte-for-byte.
- `.codex/archive/backlog.md-20261027-213700.md` — original Git blob `0a40f0a9b26d7bebb7125a790995db6b84181a4f`; earliest handoffs preserved.


- [x] PR #269 GUI UX: selected/visible clipboard copy for ChatGPT debugging, sanitized fixed-code/counts, unknown values redacted, <=100 item cap; tests and usage docs updated.
- [x] P2 remediation: normalize integer PK to JSON meter string row keys (including scheduler), test actual meter-file locking; active writeback errors override recovered marker and re-open old resolved review.
- [ ] Final exact-HEAD Hosted Linux/Windows, secret scan, formal Codex Review; operator Windows acceptance and explicit high-risk owner merge authorization required.


- [x] PR #269 detailed debugging export: opt-in full diagnostic packet with sourced UTC event chronology, mode/run identity, queue/role receipts, per-item correlated LLM timings/tokens + separate run-only events, optional identifying paths/Run ID/row ID, bounded readonly readers and sensitive-data exclusion; headless tests/docs.
- [x] Correct Row Merger and orchestrator integer-PK writeback-failure meter mutation to str(_pk), preserving item_dir for GUI inventory; register queue-recovery quality events.
- [ ] Exact HEAD Hosted E2E/Windows tests, changed-line secret scan, formal Codex review CLEAN; physical GUI acceptance #266 and explicit high-risk owner merge authorization. No automatic merge.
