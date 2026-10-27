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


## 2026-10-24 GUI archived event continuity remaining risks (unmerged PR)

- GUI background reader still depends on manual stopped-producer rotation: it **does not** make rotation safe while Tk/window and writers are live. Initial archived replay has cost proportional to the archived event count; archive SHA256 verification is performed on load and metadata-detected generation change, not continuously every second. An adversary who alters content and successfully forges unaltered file metadata may evade this lightweight per-poll detector. Offline full report offers slower authoritative archive re-verification.
- Reader retains per-run distinct event IDs/document decisions in memory, which can grow with event volume; bounded-memory checkpoints/summaries and ongoing retention/rolloff need their own correctness design. A malformed complete line degrades, and partial live tail is excluded until finished. Windows Tk visual behavior remains untested on the Linux host; no actual UI screenshot/Windows selfhosted or live LLM/ES acceptance may be claimed.


## 2026-10-25 GUI quality read budget limits (unmerged PR)

- Budgeted read-side event cardinality (50k), approximate identity codepoint count (4m) and max single JSONL line bytes (64 KiB) prevent several obvious unbounded retained allocations and decode spikes but do NOT cap Python RSS: references, Unicode storage, dictionaries/sets, parse temporaries, initial double-accumulator replay and library overhead can exceed simple budget counts. Thresholds require production resource profiling on Windows/Tk before claiming specific RAM values.
- On GUI capacity exceed, partial accumulated statistics are suppressed and raw audit/JSONL archives untouched. Offline report remains unlimited and could require substantial memory on huge logs; plan accurate bounded-disk checkpointing separately, with event-id dedup, recovered document decisions, and external trust anchor before considering destructive retention. This task does not make online rotation safe and does not assert Windows/Ollama/ES acceptance.


- Codex P2 for PR #233 observed pathological replay/rehash of an unchanged over-cap archive on each GUI poll. The new attempt caches unchanged failure-generation metadata and reraises unavailable status cheaply; changed metadata rechecks, and raw source files remain untouched. This optimization relies on the same bounded file metadata identity used in routine GUI polling; attacker-induced same-stat content forgery may evade immediate refresh. A complete offline report remains authoritative for sealed-history verification. Fresh Hosted CI + Codex review must validate the follow-up change before claiming closure.


- Post-Codex findings identified two additional fail-closed history corner cases at PR #233: first over-cap read losing active existence, and concurrent mutation invalidating capacity cache plus observed archive history. Proposed fix separates persistent observed archive/active state from the retry cache and verifies that disappearance of observed active has an inode-matching new shard. Avoid recording bogus archive high-water when integrity verification itself failed, to permit a known valid sealed ledger to be restored. New regressions exist; these are **not accepted or released** until latest Hosted CI and formal re-review pass.

### 2026-10-27 offline SQLite disk-spill boundaries (unmerged)

- Temporary SQLite stores *raw* event/document identity keys during one offline report. Restrict to trusted local OS account/disk and protect swap/backups; abnormal process kill or OS crash may leave residual bytes. Physical SQLite spill reduces Python identity-map growth but **is not** an absolute RSS bound; single-line JSON decoding, SQLite pager/cache and other processing still allocate memory.
- Spilling identities may increase disk usage and processing latency on large reports. No persistent/restartable checkpoint, source manifest binding, safe shard retirement, online rotation or Windows performance testing. Hosted Linux CI and Codex acceptance still pending; do not claim released.

### 2026-10-27 PR #234 first formal Codex P2 findings (remediation awaiting acceptance)

- Initial temporary SQLite implementation could leak sensitive local temporary paths through `TemporaryDirectory()` creation outside the sanitizer or `cleanup()` throwing an OSError. Remediation translates both to constant path-free ValueError and keeps cleanup best-effort; forced termination still may leave index remnants.
- JSON-escaped lone surrogate event/document IDs were originally accepted by `json.loads` but could fail on SQLite UTF-8 membership lookup before the old `json.dumps(... ensure_ascii=False).encode("utf-8")` rejection. Remediation returns membership false for unencodable event IDs, retaining old bad-line classification and continuation. **Exact-head Hosted regressions and formal Codex re-review are pending.**

### 2026-10-27 benchmark measurement limitations (unmerged)

- `tracemalloc` instruments Python allocations and adds overhead; it excludes non-Python SQLite/OS caches. Platform high-water RSS includes interpreter baseline and is unavailable on Windows through Python `resource` (returned as null). SQLite final main DB bytes are **not** cumulative disk writes, transient journal, OS page cache, or a guarantee of zero remnants on forced termination.
- Repeated real-file digest parity only detects source changes altering the output; stop producers and rotation before measurement. Timed region excludes subprocess startup/imports, and a few repeats cannot establish statistical performance superiority; representative stopped real runs and Windows/RSS tests are separate. Private temporary disk must be trusted. CI and Codex still pending.

### 2026-10-27 PR #235 formal review findings (remediation awaiting Hosted re-review)

- P1 (repo rule): conditional Unix `resource` and report imports previously appeared inside try blocks. Now report import is at module level and `resource` imported only on supported Unix platforms outside try; only measurement errors are caught. Windows resource unavailability leaves RSS=null.
- P2 (privacy): argparse's default failure text reflected accidentally supplied private paths/run names from `--repetitions` / `--timeout` / unknown positionals. New sanitized parser prints only fixed `quality benchmark: invalid arguments` and exit 2. Physical real-child tests added. Newest-head CI and Codex re-review still pending.
