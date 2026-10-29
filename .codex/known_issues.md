# Known Issues — Current / Operator-Gated

## Current Acceptance Reconciliation — 2026-10-28

- PR **#240** (six-file archive compaction) was user-approved and merged `21ae2cb690031c6409fd05f5cf6e4109a21548e1`; formal Codex 0 Findings, 6/6 Threads resolved, PR/main Linux E2E passed.
- PR **#241** (quality summary manifest export guard) was user-approved and merged `fb713365b173378ba8ca82e0557e4fdd5a415650`; Codex 0 Findings, 1/1 Thread resolved, PR/main Linux E2E passed.
- PR **#242** (failure report cross-folder ledger guard) was user-approved and merged `e010a5e07c45016f8f0ab4094c30bcd33825d3b5`; Codex 0 Findings/Threads, PR Linux #40622149444 and main Linux `offline-e2e` #40623677955 SUCCESS. All old `pending` labels in dated findings below are historical *at the time of review*, not current outstanding engineering tasks.
- Remaining issues: Windows self-hosted 3.10/3.11 still queued/operator-deferred, independent OPEN PR #231, no real Windows/Ollama/ES readback, no crash-safe authenticated checkpoint/online shard retirement. These accepted PRs do not prove absence of filesystem races or malicious-tamper resilience.

## Environment and External Dependencies

- Windows 3.10 and 3.11 self-hosted runners remain **queued**; Linux Hosted `offline-e2e` is the operative independently reported test. Physical Windows PSAPI/GUI/LLM/SQL Server/ES operation remains operator-deferred. Do not label full workflow green.
- Pinned `peft` dependencies may be blocked by proxy HTTP 403; clean offline Linux E2E uses `requirements-e2e.txt`. Local environments may lack YAML/OpenCC/tqdm. Do not treat such install limitations as working integration proof.
- Historical ES persisted metadata might contain sensitive model specs or old API credentials. New allowlisting cannot retroactively redact history; operators must rotate and reindex in controlled deployment.
- Windows legacy multiprocessing occasionally triggers `EOFError` or `WinError 5 DuplicateHandle`; thread fallback/reap mitigate but physical Windows tests remain unaccepted. `datetime.utcnow` warnings are nonfunctional technical debt.

## Semantics and User-visible Quality Boundaries

- Per-run `processing_quality_events_*.jsonl` is an observational log, not a transactionally authoritative audited writeback record. Partial tails, corrupt complete lines, duplicate IDs, retention/cardinality overflow and generation changes have distinct fail-closed statuses. Manifest SHA256 ensures self-consistency *after sealing* only, not signature or retroactive trust.
- Manual numbered shard rotation requires the operator to stop all writers/readers; there is no safe automatic online writer+GUI rotation, no automatic shard deletion, no authenticated checkpoint, and no crash-safe resume guarantee.
- GUI reader budgets (50k events/4m retained identity characters/65536 bytes per line) are **capacity guardrails**, not a byte-precise memory ceiling. A failed generation may be cached for efficient repeat rejection, but no partial stale counts may be displayed as valid.
- `consumer_orchestration_failure`, `row_merger_retryable_failure`, `producer_operational_failure`, `stage_orchestration_failure` and `worker_phase_failure` are fixed run-scoped catch-site observations; multiple may cover one incident. Do not sum them as distinct document failures. Typed SDK transport/timeouts are mechanistic classification only; `WORKER_LLM_CALL_EXCEPTION` does not establish provider fault. A worker may fail outside caught paths or without an exception.
- Existing `llm_call_audit_*.csv` may retain raw `error` text; restrict filesystem access. No stable historical per-request UUID, so count of request rows is not a proven logical unique-attempt denominator. A post-call local failure can yield `ok=NO` even after successful provider response.
- Explicit ES sink acknowledgement is required to claim confirmed durability. Only selected paths support it; non-acknowledging Excel/CSV or pending ES queue dispatch remain unknown, not failures/successes. Validate real stored ES writeback and reference IDs before bulk replay.

## Offline Quality Benchmark Limitations

- Temporary SQLite exact identity keys persist briefly on a local private temp file; delete on normal/error cleanup, but abnormal crash remnants and storage privacy need operator care. It is not a persistent checkpoint or retention mechanism.
- Full canonical report SHA256 parity and active/archive/manifest file stat-generation checks are required before a benchmark result; stat metadata is **not** an atomic content snapshot, lock or robust malicious timestamp/inode tamper detector. Stop writers and rotation before benchmarking.
- `median_seconds` times worker report only, `median_subprocess_wall_seconds` times parent-observed one child lifecycle but excludes parent's guard/orchestration; `tracemalloc` alters both. OS high-water RSS includes interpreter/imports, Windows `PeakWorkingSetSize` is resident working set, **not** private committed RAM, and final SQLite main DB bytes are **not** total bytes written.
- Worker/parent numeric data now fails closed on NaN/Infinity, malformed byte counts and invalid wall clocks in accepted PR #239. This does not prove real Windows DLL success, benchmark speedup, or available disk capacity.
- 1–3 controlled real Windows/Ollama/ES samples with **independent stored readback** and representative Windows stopped-run benchmarking remain pending.

## Archived History

- `.codex/archive/known_issues.md-20261027-213700.md` (exact original Git blob `f6ac56a63f63f84b74cb6b5048c88086b70b0e4b`) retains all pre-compaction historical issues, older findings, privacy/capacity caveats and previous archives. Review it only for traceability; old “PR pending” labels are not current status.

## 2026-10-27 PR #240 archival compaction Review findings (remediation pending acceptance)

- Initial clean Linux `offline-e2e` did **not** collect the new archive hash regression; this was flagged as P2. Also Windows Git `core.autocrlf=true` could rewrite .md archive checkout LF to CRLF, producing false blob-hash failures, and active ES bulk/date validation rules were lost (P1) even though archived. Remediation now places direct test in active Linux job, pins archive byte-preserving checkout via `-text`, restores ES date/precision pair and writeback acknowledgement semantics in active memory.
- Windows self-hosted runners remain queued; no Windows checkout test was physically executed. Latest-head Hosted Linux CI and formal Codex re-review remain pending. Preserve original immutable archive bytes and do not claim review closed until verified.

## 2026-10-27 PR #240 second Codex P1 safety-note (remediation pending verification)

- Two active-contract regressions were caught despite correct full history archiving: the original single-extract source fingerprint/ordered slice/dispatch identity during partial `resume`/`smart_reset` had become archive-only, and ES strict top-level `importance` lossless five-score integer/null normalization was absent from active documents. Compact snapshots are not enough when active-only readers must maintain these correctness boundaries.
- Both contracts and active-memory regression assertions were restored. Latest-head CI and formal Codex re-review are required before marking accepted; Windows physical smoke remains deferred.

## 2026-10-27 PR #240 third Code Review P2

- Original cache-aware per-request audit `cached_input_tokens`/source/stage and GUI `effective_tok_per_s_est` heuristic semantics were lost during active-memory compaction even though runtime continued to implement them. Missing provider cache metadata is unknown, not zero; same-stage stable template size is only a proxy, not proof of cache hit or isolated GPU throughput. Active contracts and regression checks restored. Latest-head CI/re-review still pending; no real Windows runner acceptance implied.

## 2026-10-28 read-only quality report export could overwrite sealed ledger (fix pending acceptance)

- The report CLI previously checked only `.json` suffix for `--output` and then used `atomic_write_json` with `os.replace`. A path named `processing_quality_events_*.jsonl.manifest.json` also passed, so exporting a summary could clobber another run's archive SHA256 consistency ledger and invalidate future verified replay. This was discovered by source inspection; no production data loss is claimed.
- Branch protection rejects reserved ledger destinations, including nonexistent ones, and symlink aliases before stream replay; real-file regression tests should verify ledger bytes and valid replay stay unchanged. Latest-head Hosted CI, formal review, and Windows actual acceptance have not yet completed. Avoid describing the SHA256 ledger as independently authenticated or the CLI guard as race-free.

## 2026-10-28 LLM failure report other-directory ledger overwrite gap (pending review)

- `llm_failure_report` previously reserved audit-like `--output` names **only** when destination parent matched the input audit directory. A user could choose another directory's sealed `processing_quality_events_*.jsonl.manifest.json` and accidentally overwrite its SHA256 ledger via shared atomic writer. No actual user data loss is asserted. The new branch rejects the canonical manifest name globally before audit CSV replay and adds physical negative tests. This is not a cross-process race-proof path sandbox. Hosted CI / Codex Review pending.

## 2026-10-28 observed local-time audit filters (review pending)

- `llm_call_audit` producer timestamps are naive `datetime.now().isoformat(timespec="seconds")` local wall clock, **not UTC**. The new opt-in `llm_failure_report --since/--before` scope preserves these literal producer-local seconds without cross-host or DST normalization. Comparing separate hosts' naive timestamps is not absolute chronology.
- Legacy CSV can have blank/missing timestamps. When filtering, a row that cannot be unambiguously placed in the chosen interval makes the entire scoped report unavailable rather than silently decreasing the denominator. Unfiltered historic reports retain existing invalid-row degraded diagnostics. Filtered call-attempt counts do not prove unique request attempts, provider faults, retries or document failures; remain operator-observational only.
- New branch's exact-head Hosted CI and formal Codex review remain pending. Windows self-hosted/real ES/Ollama readback still operator-deferred.

## 2026-10-28 audit-row UUID migration limitations (new branch pending)

- `audit_record_id` only identifies a successfully emitted audit CSV record. It cannot detect calls that failed before logging or identify two rows as the same provider retry/dispatch; legacy files may not have the field at all. A running prior-version file whose header matches the immediately preceding schema is appended in its old format; unknown older headers require explicit offline migration or a new run rather than silent corruption. Do not treat this feature as durable retry checkpoint, authenticated identity, unique request denominator or live Windows acceptance. Latest-head Hosted Linux and Codex Review pending. Historical "#244 pending" entries above are superseded by accepted merge `9e743267676af6fc956eca3917253527797785ec`.

## 2026-10-28 Worker-side call-ID scope (pending review)

- `worker_call_id` identifies one explicit application Worker `CallLLMAPI` invocation only, not an HTTP-level provider request: an SDK may retry internally, and failed pre-call selection/mock/cancelled jobs have no such ID. A crash or an audit append failure may omit the record. This metadata does not create a retry-family ID or unique document failure denominator, nor prove successful ES/SQL persistence. The append writer accepts exact newest plus two prior CSV headers, but no automatic legacy schema migration or external cross-process lock is introduced. Latest-head Hosted Linux and Codex Review pending; Windows/Ollama/ES operator-gated. Previous #245 pending issue is superseded by accepted merge `bc0a46ababa40f67004659a0b15dd0b29cd31303`.

## 2026-10-28 wrapper-return audit evidence limits (pending review)

- `call_llm_api_returned` reports a Python `CallLLMAPI` function return, not remote provider HTTP success; SDK internal retries and remote processing before a timeout remain unobserved. The flag is unknown/blank for non-Worker logging; post-call JSON repair/persistence can cause `ok=NO` even when the function returned. Worker exceptions before dispatch, forced termination, failed audit writes or out-of-process processes can leave missing evidence. Schema compatibility accepts only complete exact prior three headers and retains old widths. Do not use this signal as a unique retry or affected-document denominator, authenticated checkpoint, full Windows acceptance or ES/SQL readback. Latest-head CI and formal Codex Review pending; older #246 in-progress labels superseded by merged main `0b380ae65d9bc0b388b66bfa8a6c216ca8e0782d`.

## 2026-10-29 limitations of source-verified split family IDs (pending review)

- A `split_family_id` is created only for explicit persisted split-intent of invalid JSON, not general Worker requeues, same-prompt redispatch, SDK HTTP retries or logical document success. Journal SHA256 and random UUID offer local consistency, **not authentication**, and evidence may be interrupted between intent write and two child file installs. Legacy v1 journals lack IDs and return unknown until a later explicit write, without claiming historical attribution. Reader validates direct parent/child and bounded non-symlink journal but is not an adversarial, race-free filesystem sandbox. No remote Ollama/ES/Windows/Tk acceptance, and no affected-document denominator or provider/sink confirmation. Hosted CI and formal exact-head Codex Review pending at implementation; #231 untouched.

- Initial PR #248 exact-head Codex review exposed four important P2 lineage risks: old nested UUID after replaced parent source; symlink alias in identity/splits directory; oversized nesting within size budget; and non-v4 placeholder IDs. Fixes and new tests were committed on the PR branch, but do not claim closure until fresh exact-head Codex review and Hosted Linux tests. Metadata is still unauthenticated and directory checks are not race-free against an active malicious local operator; no automatic production retry accounting.

## 2026-10-29 Worker family correlation limitations

- Streaming source check and journal hashes are not authenticated or race-free across a concurrent source-file replacement; no generation-locked transaction, no crash-proof audit writer. Call failures before CSV append may be omitted. Same-content generations and generic requeues, SDK internal HTTP retries, historical v1 journals without family IDs, sink readback and true unique-document failure denominators remain unproven. Invalid/absent/symlink sources and corrupt lineage produce unknown. Windows/Ollama/ES operator validation still deferred; new PR Hosted Linux and formal Codex pending.

## 2026-10-29 #231 reconcile: stopped-producer JSONL recovery limitations

- Manual recovery is only for one extra consecutive newline-complete, unsealed JSONL shard outside an otherwise verified SHA256 manifest and with no active file. It requires stopping all writers/GUI, explicit CLI confirmation, exclusive hardlink naming and post-link SHA256 check. Unsigned ledger or extra shard cannot authenticate event provenance; symlink/active collision, missing/corrupt manifest and multiple extras fail closed. It cannot prevent races with noncooperating external writers or guarantee Windows hardlink support. An interrupted link/unlink leaves an ambiguous state for human inspection; no automatic cleanup. Old #231 Linux/Codex evidence predates latest `main`, so exact-head re-review and Linux CI are pending, Windows operator-gated.

- **2026-10-29 #231 exact-head formal Codex P2 (4011aced):** An extra unsealed candidate may be a preexisting hardlink to a sealed archive or unrelated file. Restoring it into writable active would mutate the sealed inode on later append and invalidate its SHA256 manifest. Check candidate `st_nlink == 1` in read-only inspection and again under the writer lock just before exclusive link; ensure exactly two names of the same inode immediately after linking. Fail closed without unlink; add real sealed-shard and outside-alias hardlink regressions. This is an operator-stopped assumption, not a race-free adversarial filesystem guarantee. Linux CI #40813732502 PASS applies only to prior SHA; new review and Hosted Linux CI required.

## 2026-10-29 observed queue events (pending review)

- Queue observations can be absent after a crash between atomic rename and event write, or on unsupported hardlinks, permission faults or competing filesystem editors. Only explicitly instrumented queue transitions are represented; worker-stage direct moves, SDK HTTP retries and sink operations are not counted. SHA256 source/name digests are not a privacy anonymity guarantee for guessable input. Event data has no authentication or cross-process lease; same filename/text does not prove a common retry generation. Do not compute retry rates, source-doc success rates or provider attempts from these counts. Windows real integration and Linux exact-head CI/review pending.

- **#251 first exact-head P2:** Queue event read-only validator initially accepted arbitrary text as `observed_at_utc`; such a corrupted record would incorrectly count as a valid observation. Require a parseable timezone-aware UTC offset zero, reject malformed/naive/non-UTC values, retain observed-count fail-closed contract; add real-file negative tests. New SHA needs fresh Hosted CI and official review, not inferred from predecessor.
