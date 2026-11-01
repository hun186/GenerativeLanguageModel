# GenerativeLanguageModel — Active Backlog

## Current Summary
- **Accepted baseline:** main `e010a5e07c45016f8f0ab4094c30bcd33825d3b5`, Linux offline-e2e #40623677955 **SUCCESS**; PR #239 commit `46b7c7290417421a6dc09e114f82c1066ce0179d`, #40513712390 **SUCCESS**; #231 is closed/merged (confirmed merge `21f8ea5fc985171d5ae2287416f0ff5a8b012d63`). PR #240, #241, #242 already accepted/merged, never reopen. Windows selfhosted / operator real NTFS/SMB remains **operator-deferred**.
- **Latest accepted queue main:** #269 owner-authorized Squash Merge `d22585b92be9b61d437cfba209902dade91c20d7` on 2026-11-01, exact reviewed HEAD `c5668c123e76ab5b85bd6506a3a505663cbbf641`; #267/#268 accepted earlier. Older dates and historical findings remain in archives.
- **#269 merged, operational acceptance pending:** Safe strict enumeration, bounded retry, quarantine, finite recheck, healthy-row continuation and queue-integrity meter are in merged code. Verified pending markers must not be treated as sink Success. Operator Windows/SMB/live production acceptance is NOT VERIFIED (#266).
- **#269 merged GUI feature:** shared Windows `win_gui.py` incident review and collapsible per-document progress, with bounded strict Meter readers, detailed clipboard diagnostics, and review-only append ledger. Headless GUI/API tests passed Hosted CI; physical interactive Tk acceptance remains Issue #266. Actions never delete source, authoritative hold evidence or SQL/ES sinks.
- **#269 completed owner merge gate:** latest-head Linux E2E, Windows Hosted 3.10/3.11, changed-line scan SUCCESS, formal Codex receipt no major issues, 22/22 threads resolved, explicit 2026-11-01 owner instruction to merge, GitHub confirmed Squash Merge. Two self-hosted jobs were queued and not treated as verified; physical operator tests remain separate.

## True Open Engineering Work
- [x] PR #269 exact-head Hosted Linux E2E, Windows 3.10/3.11, secret scan, formal Codex Review, owner approval and Squash Merge accepted; physical operator acceptance is separate #266.
- [ ] **Issue #266:** real operator Windows/SMB/NTFS, live Ollama, SQL/ES sink-ack/readback and Tk GUI interaction acceptance. Hosted CI is not physical operator acceptance; no unverified Windows auto-replay.
- [x] **Historical PR #231** is closed/merged (`21f8ea5fc985171d5ae2287416f0ff5a8b012d63`), independently verified from GitHub. Do not reopen stale historical work.
- [ ] Native production writer-quiescence/stop evidence, authenticated replay identity and generation-bound checkpoint before any auto source rebuild or queue cleanup; never assume a stale RUNNING worker is safe to replay.
- [ ] Add central all-project incident inventory only if user requests beyond current-run structured queue recovery/writeback codes; preserve privacy and per-run scopes. Optional owner-directed notification, not a silently installed service.
- [ ] Durable error stream for non-schema Producer/Worker/Stage/Row-Merger failures, authoritative request/retry lineage and correct denominator; do not infer document failure from audit rows or cached tokens.
- [ ] Verify GUI/Tk/PSAPI PeakWorkingSetSize, partial metric reporting and restart-capacity behavior on actual Windows; never mark partial results complete.
- [ ] Audit ES event_ids/date-precision/stage lineage with independently confirmed sink readback; preserve source, repaired and acknowledged distinction.
- [ ] Evaluate crash-safe checkpoint/identity, bounded reduction disk state, GUI observability and cache only after demonstrated need. Never change sensitive config or unsafe API keys.

## Recent Changes (historical progress notes; older Pending labels are superseded)
- 2026-11-01: PR #270 Codex P1 remediation preserved exact original project, memory, and backlog snapshots; this PR's Hosted CI/Review remain independent pending gates.
- 2026-11-01: Reconciled exact #269 Squash Merge with Hosted GitHub. Remaining next focus: Issue #266 operator-owned offline NTFS fixtures, then separately gated physical GUI/SMB/live sink evidence. No automatic production queue or data writes.
- 2026-10-28 to 2026-10-31: #243–#265 concluded in historical archived handoffs; staged Windows native safe-handle probes, queue no-clobber, identity and queue-inspector work. Operator Windows acceptance #266 still pending.
- 2026-10-31: #268 merged. #269 staged strict restart, three-attempt retry, per-item blocked/incomplete, five 30s cooldown rechecks, persisted operator escalation and metadata-only supervisor CLI.
- 2026-11-01: #269 GUI management and review-only audit ledger; hard safety veto on marking active blocked/writeback failures as resolved; fixed missing GUI polling callback and duplicate recovered-item adoption. **All still pending final acceptance.**
- 2026-11-01: **Archive-first compaction**: preserved the complete 205-line prior active backlog verbatim in `.codex/archive/backlog.md-20261101-124200.md` before reducing this active summary to within 200 lines / 40 KB. Retain all old open handoffs and review traces in immutable archive.

## Archived History
- `.codex/archive/backlog.md-20261101-234800.md` — exact pre-PR #270 active backlog Git blob `869d39e0b2ba37a1e2691c5a3a1cc051be41e6bf`, preserved without changes; #269 merge reconciliation replaces dated Current Focus/Handoff text only.
- `.codex/archive/backlog.md-20261101-124200.md` — full original #269 development chronology, old active backlog immediately before latest compaction.
- `.codex/archive/backlog.md-20261028-104900.md` — original Git blob `67b64c801806d585e246d9f0091efe4cb69d37ef`; pre-reconciliation work preserved byte-for-byte.
- `.codex/archive/backlog.md-20261027-213700.md` — original Git blob `0a40f0a9b26d7bebb7125a790995db6b84181a4f`; earliest handoffs preserved.


- [x] PR #269 GUI UX: selected/visible clipboard copy for ChatGPT debugging, sanitized fixed-code/counts, unknown values redacted, <=100 item cap; tests and usage docs updated.
- [x] P2 remediation: normalize integer PK to JSON meter string row keys (including scheduler), test actual meter-file locking; active writeback errors override recovered marker and re-open old resolved review.
- [ ] Final exact-HEAD Hosted Linux/Windows, secret scan, formal Codex Review; operator Windows acceptance and explicit high-risk owner merge authorization required.


- [x] PR #269 detailed debugging export: opt-in full diagnostic packet with sourced UTC event chronology, mode/run identity, queue/role receipts, per-item correlated LLM timings/tokens + separate run-only events, optional identifying paths/Run ID/row ID, bounded readonly readers and sensitive-data exclusion; headless tests/docs.
- [x] Correct Row Merger and orchestrator integer-PK writeback-failure meter mutation to str(_pk), preserving item_dir for GUI inventory; register queue-recovery quality events.
- [ ] Exact HEAD Hosted E2E/Windows tests, changed-line secret scan, formal Codex review CLEAN; physical GUI acceptance #266 and explicit high-risk owner merge authorization. No automatic merge.


- [x] PR #269 Windows shared GUI: paged collapsible per-row/document progress, 10-unit visual bars, selected native progress bar, priority statuses/filters/search, low-duty expanded-only background meter worker, no false writeback success. Scheduler/Consumer/Row Merger status+timestamp evidence and headless tests/docs included.
- [x] Prior P2s: >500 review rows now paginated with known failures prioritized; old timezone-naive LLM audit lines explicitly marked unknown local timezone and not sorted into UTC chronology, future writer offset-aware. Regression tests included.
- [ ] Latest-head CI and formal Codex review; Windows DPI and live LLM/SQL/ES/NTFS operator acceptance Issue #266. High-risk PR #269 must remain unmerged without owner permission.

- [x] Formal Codex P2 remedies: per-row Unix epoch validator independent of slice counters; strict bounded 5-attempt run-meter read that raises on corrupt/permission failures and preserves previous GUI data, never falsely showing zero work. Added regression cases for 2026 epoch, invalid JSON, transient recovery, last-good display.
- [ ] Latest-head Hosted CI and exact-head Codex Review must PASS/CLEAN; Issue #266 Windows live GUI acceptance; require explicit high-risk owner Merge authorization.


- [x] Codex P2 on incident review: use shared strict Meter reader rather than default-empty meter_read; invalid existing JSON propagates, UI retains last valid incident list, explicit old item directory works only for missing meter. Real-file corruption/recovery and UI regression tests added.
- [ ] Exact-head Hosted CI, no P1/P2 formal Codex findings and owner-approved high-risk Merge remain required.


- [x] Formal Codex P2 (dd757864): detailed ChatGPT diagnostic clipboard must not use default-empty load_meter.meter_read. Now shares strict bounded reader, marks unavailable input and unknown counts explicitly, with actual-file corruption/restoration/missing/unsafe tests.
- [ ] Exact-head full Hosted CI + clean formal Codex Review and explicit owner authorization before merge of high-risk #269.
