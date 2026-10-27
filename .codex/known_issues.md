# Known Issues — Current / Operator-Gated

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
