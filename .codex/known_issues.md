# 已知問題（Known Issues）

## Current Summary — Open / Operator Required

- **Requirements install proxy limitation:** `python -m pip install -r requirements.txt` may fail cloning pinned `peft` via proxy HTTP 403. Targeted Hosted `requirements-e2e.txt` Python 3.11 offline-e2e is the operative CI gate; incomplete local environments can be missing YAML/OpenCC/tqdm.
- **Historical ES secrets:** older ES documents/snapshots may contain stringified model specs and API keys. Runtime redaction does not clean existing data; rotation and controlled reindex remain operator actions.
- **Windows legacy multiprocessing overlap:** `EOFError` / `WinError 5 DuplicateHandle` mitigated by short reap and thread fallback, but `test_windows_spawn_overlap_join_clear_allows_pool` expectation mismatch and actual Windows smoke remain open.
- **Windows self-hosted unavailable:** 3.10/3.11 CI jobs remain queued; user explicitly defers them. Never imply real Ollama/SQL Server/ES persistence or GUI visual verification from Linux offline CI.
- **datetime.utcnow** deprecation warnings remain a nonfunctional follow-up.
- **ES real sink coverage:** only explicitly acknowledged writeback can increment confirmed sink counters (currently selected ES paths); Excel/CSV no durable acknowledgement means unknown, not failed or confirmed. Strict multidimensional Event local references, article-date provenance and malformed source preservation must continue to fail closed.

## Current Quality Observability Limitations

- The per-run Processing Quality JSONL, strict writer/reader/GUI/offline report are observational, not transactionally consistent archival proof. Corrupt complete JSONL lines degrade the report; incomplete tails are excluded. Bounded file-edge fingerprints cannot detect all adversarial in-place interior edits.
- Per-request `llm_call_audit_*.csv` may retain raw `error` text: restrict access. The legacy CSV has no request UUID; historical deduplicated request counts cannot be claimed. Request rows with `ok=NO` can reflect local post-call processing/persistence failures, not necessarily provider failure.
- `consumer_orchestration_failure`, `row_merger_retryable_failure`, `producer_operational_failure`, `stage_orchestration_failure` count catch/retry-site observations, not distinct failed documents. Stage Runner may perform model calls or local work; generic Runner exceptions are not automatically non-LLM.
- **PR #226 pending acceptance:** `worker_phase_failure` records fixed leaf execution-site codes only. `WORKER_LLM_CALL_EXCEPTION` means exception arose inside the `CallLLMAPI()` invocation, NOT proven provider outage. Failures that return `ok=false` without exceptions, mock-only faults, unexpected process kills, and exceptions outside caught `proc()` are not comprehensively covered; mock/cancellation are excluded from this event taxonomy.
- One failure may produce CSV/Worker/Stage/Producer events at different catch sites. Do not add counters to infer logical failed document count, API-call failure rate or unique incidents.
- Need 1–3 controlled real Windows + Ollama + ES rows with independent readback before replaying bulk workload; complete Worker root-cause drilldown and rotation/resume remain future work.

## Recent Changes

- 2026-10-23 #224 corrected misclassified schedule bookkeeping exceptions and re-propagated cooperative cancellation when cleanup fails. Hosted Codex and Linux CI later passed; user-approved merge.
- 2026-10-23 #225 Stage preparation and escaped Runner exception telemetry, exact-head Codex 0 Findings and Linux E2E success, merged into `e9a7e549205323b310ba7063cde5e39b0f5e1e01`. Main Linux E2E after merge passed.
- 2026-10-24 #226 leaf Worker phase telemetry/tests prepared for independent Hosted acceptance. Scope is observability only, not live provider diagnostics.
- 2026-10-24 compaction: prior full issue file was archived before active rewrite; all historical issues, PR findings, and previous issue-status snapshots preserved unchanged.

## Archived History

- `.codex/archive/known_issues.md-20261024-before-pr226-review.md` — complete pre-compaction known issues, prior PR #213–#225 findings and historical context.
- `.codex/archive/memory.md-20261024-before-pr226-review.md` — full project history and earlier archive references.
- Earlier archives remain under `.codex/archive/`; historical pending statuses are not current Hosted authoritative states.

## 2026-10-24 typed SDK failure observability caveats (PR pending)

- The OpenAI-compatible SDK can emit timeout/connection errors for *local* client/transport issues as well as inaccessible remote providers. HTTP 4xx/5xx proves only an HTTP status was returned, not whether the actual model runtime caused it. `APIResponseValidationError` indicates SDK response interpretation trouble but not necessarily malformed generated model text. This telemetry deliberately avoids causal claims.
- The existing `CallLLMAPI` wraps typed timeout/connection SDK exceptions into `RuntimeError`; classifier is limited to typed direct causes, not error text. SDK retries may perform multiple HTTP calls before one Worker incident is written. Fatal crashes/process kills, non-exception `ok=false`, API request counts and on-disk persistence remain outside this work. The raw legacy request CSV may include exception text and remains access-controlled.
- Offline/mock-transport and Hosted Linux CI are not proof of successful Ollama/Windows/ES integration. Those operator acceptance checks remain deferred.


## 2026-10-24 run-scoped incident diagnostics caveats (new PR)

- Incident family composition is only the relative mix of *accepted run-scoped incident observations*, not a failure rate per LLM/HTTP attempt, slice, document or distinct cause; different catch sites can observe one logical error. Zero incident observations give unknown percentages, and n<30 remains advisory.
- Complete malformed JSONL records are excluded with degraded completeness; incomplete writer tails are excluded and flagged. Existing `QualityTailReader` per-poll bounded file edge checks do not provide adversarial archival integrity. Historic reports still include the existing `log_file` basename; avoid embedding private identifiers into audit run IDs.
- Windows self-hosted 3.10/3.11, real Ollama/ES writeback and independent ES readback remain unavailable in the agent Hosted CI; only Linux offline tests are claimed after their actual run completes.


## 2026-10-24 manual JSONL rotation operational constraints (unmerged PR)

- Rotation explicitly **requires all producers and GUI readers stopped by operator**. Lock serializes cooperating writer calls during rename but cannot stop external noncooperating editors. Live GUI `QualityTailReader` still sees only active file and its counters may reset after manual rotation; use offline report for full archive+active history until separately designed live cross-generation reader.
- No durable manifest/sequence seal yet: gap detection catches removed intermediate indexes but cannot prove that a highest or all segments were deleted, nor authenticated integrity of historical bytes. Never silently garbage collect archives. A corrupt archived record causes degraded reporting; incomplete archived tail is explicitly degraded, not proof of intact history.
- First-stage implementation is bounded to 64 numbered segments and manual no-deletion. Auto retention/pruning, crash-safe manifest, secure concurrent live rotation, Windows/junction tests, actual Ollama/ES round trips and in-place logfile archive replay under highly concurrent production writers remain unverified.


## 2026-10-24 archive manifest stage 2 limitations (unmerged PR)

- SHA-256 manifest detects accidental archive corruption/loss **only from first sealing onward**. It is unsigned and locally co-located, not an audit-grade trust anchor: an attacker with access to archives and ledger can recompute hashes; deleting both prevents detection without external reference. Initial trust-on-first-use cannot attest to historical deletions. Active stream changes remain outside the sealed-shard digest until manually rotated.
- Crashes after archive rename but before ledger publication leave a mismatching manifest that prevents false-success reporting; operator repair/reconciliation is a separate future task. Runtime exceptions before ledger publish attempt to roll back rename while holding writer lock; uncooperative writers and platform crash durability are not proved. No automatic deletion/retention, no on-the-fly GUI replay, no Windows junction acceptance, no live Ollama/ES readback.
- Offline reports require hashing sealed archives (twice for mutation detection), increasing I/O proportional to archive size; max 64 shards and 24 KiB ledger enforced. Legacy shards remain explicitly `unsealed_legacy`, not verified.
