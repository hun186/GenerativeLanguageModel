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
