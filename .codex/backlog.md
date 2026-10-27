# GenerativeLanguageModel — Active Backlog

## Current Summary

- Reduction Engine v1 A–L is complete, including PR #200 documentation/release closure; #203 optional transient semantic cache remains intentionally **deferred** pending observed duplicate-call savings.
- Issue #211 corrected via user-accepted #212/#213, which passed focused offline SQLite/Excel E2E. This is not independent live Ollama/ES readback.
- Quality telemetry/GUI/JSONL/benchmark PRs #218–#230 and #232–#239 are accepted on main as of `46b7c7290417421a6dc09e114f82c1066ce0179d`; historical unchecked checklist entries for those already-merged PRs are superseded, **not reopened**.
- PR **#231** remains OPEN, unmerged, mergeable=false (head `a8711e9337b62e4b9c6ad62f37ba3e78ba4e8fea`), independent from all new development. Do not auto-merge or rebase.
- As of PR #239 postmerge Hosted CI #40513712390, Linux `offline-e2e` SUCCESS; Windows 3.10/3.11 queued/operator-deferred. Overall workflow is not marked green because those runners are missing.

## Active Work — In Progress (separate PR)

- [ ] `docs/codex-active-memory-compaction-20261027`: archive exact six pre-compaction `.codex/*.md` files, preserve blob hashes and past review/commit evidence; condense dated historical “pending” notes without changing effective program/API rules, safety or uncompleted backlog. Verify snapshots, CI and exact-head official Codex Review; **wait for explicit Merge authorization**.

## True Open Engineering Work (not silently completed)

- [ ] PR #231 interrupted sealed JSONL rotation no-clobber rollback: investigate mergeability/branch drift independently; only merge with explicit user approval and current-head test/review evidence.
- [ ] Operator Windows real native PSAPI `PeakWorkingSetSize`, GUI visual, and several representative *stopped* full-run memory-vs-SQLite performance repetitions. Linux simulated Windows API tests do **not** complete this.
- [ ] Operator-controlled 1–3 real Windows+Ollama+Elasticsearch rows, independent ES readback and state/lineage/structured Event ID/date validation before replaying any large production workload. Confirm deployed binary commit includes accepted writeback fixes. Only then characterize bulk pending/confirmed/latency/token cost.
- [ ] Complete distinct LLM request error classification / effective retry and failure denominators (legacy request CSV lacks stable request UUID; catch-site JSONL cannot imply unique affected document). Add bounded privacy-safe drilldown/time windows only with source-authoritative identity/evidence.
- [ ] Deepen actual Producer/Worker/Stage/Row Merger **non-schema** root-cause taxonomy and cancellation semantics where not yet attributable; existing Worker SDK subcodes provide *mechanism hints*, not provider fault guarantees.
- [ ] Design crash-safe authenticated exact disk checkpoint and generation-bound replay/resume with stopped/online producer safety before any automatic shard retirement, pruning, or online rotation. Existing temp SQLite spill and self-consistency SHA256 manifest are **not** substitutes.
- [ ] Engineer GUI restartable bounded checkpoints/disk-backed identity cache only after strong correctness and physical restart tests; capacity-exceeded must remain unavailable rather than dropped events/partial percentages.
- [ ] Consider opt-in legacy unmarked runtime/checkpoint inventory/migration (GC must not silently adopt old files) and finer reduction checkpoint locks *if* measured evidence warrants them.
- [ ] Evaluate whether `utils/utilities.py` is still an active dependency before gradually refactoring behind compatibility re-exports; avoid speculative rearchitecture.
- [ ] Consider verified ES buffered bulk acknowledgements and sink writeback semantics without mistaking dispatch/refresh visibility for durable persisted confirmation.
- [ ] Retain operator-deferred Windows self-hosted CI and a truthful separate Linux `offline-e2e` acceptance gate; never equate queued overall workflow to full acceptance.

## Accepted Recent History (supersedes past unchecked rows)

- #233 GUI over-cap stat-cache merged `8d4a967e29dbda8d845f30dde435e2883f9b9b3c`.
- #234 opt-in offline SQLite identity spill merged `4d34ac790a4511963d1b191cd495f459f9bee341`.
- #235 resource/performance benchmark merged `6cba3ef417047f07a2c3e8b46bd0ac36e7d2fd64`.
- #236 benchmark physical source generation guard merged `6c5cda3b51fab14049edf540b65f30a59f2fb7ef`.
- #237 Windows resident working-set reading merged `1757570e0c40d331d7a55ece386089309f13cd10`.
- #238 parent-clock complete child wall-time merged `3cabaa4baa475d4d3566d552d6a5a53cae0fb1a8`.
- #239 strict finite benchmark measurements merged `46b7c7290417421a6dc09e114f82c1066ce0179d`.

## Archived History

- `.codex/archive/backlog.md-20261027-213700.md` (exact old Git blob `0a40f0a9b26d7bebb7125a790995db6b84181a4f`) retains **all** previous checked/unchecked tasks, historical PR staging, CI run IDs, heads, reviews and prior archive links. Some old unchecked tasks refer to features since accepted; reconcile with current main before reviving work.
- Earlier archives are unchanged and remain traceable.

## PR #240 formal review remediation (2026-10-27)

- [x] First Codex exact-head `c614674644d35bcdc16ac47b685d2a00d145c0ff`: **1 P1 and 2 P2**. P1 ES publication date/precision, Event link and buffered writeback acknowledgement contracts were absent from current active memory. P2 Windows autocrlf changed archived Git blob checkout bytes; active Linux `offline-e2e` did not execute new archive tests.
- [x] Restored concise ES contracts in `.codex/{api_contract,decisions,architecture}.md`, added `.gitattributes` `-text` for exactly the six immutable archives, included focused archive tests in Linux `offline-e2e`, expanded regression assertions.
- [ ] Verify **remediated latest HEAD** Linux `offline-e2e`, request formal `@codex review` and confirm P1/P2 removal; reply to/resolve all three prior review threads only with corroborating CI and reviewer acceptance. Await explicit Merge instruction. PR #231 remains independent OPEN; Windows real runner acceptance remains operator-deferred.
