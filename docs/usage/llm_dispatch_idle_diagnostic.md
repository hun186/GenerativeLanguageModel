# LLM dispatch idle evidence — local read-only diagnostics

Use one of the repository-root launchers:
- Windows: run_llm_dispatch_diagnostic.bat
- Linux: bash run_llm_dispatch_diagnostic.sh

Windows: **double-click** `run_llm_dispatch_diagnostic.bat` (no arguments) to show a
Traditional Chinese, read-only summary of available evidence. The console
stays open until a key is pressed; it does not claim GPU measurements or
silently treat missing input as a passing result. To see options without an
extra pause, run `run_llm_dispatch_diagnostic.bat --help` in a terminal.
Arguments are still forwarded verbatim. Add `--human` with arguments to get
the Chinese summary instead of default machine-readable JSON. The summary
shows the source label (default `logs` / explicitly selected `--logs-dir`),
not any private absolute path, raw endpoint, PK, run ID or error detail.

Both use Python 3.10+ (stdlib only) and default to the repository's ./logs.
If the actual PGMSubDir is elsewhere, supply its logs directory:
    python scripts/diagnose_llm_dispatch_idle.py --logs-dir <runtime_logs_directory>

### Multiple run-specific metadata directories (Issue #302 read-only Phase 1)

If Queue Meter, endpoint leases, and LLM Audit are stored in different logs
roots, select **each actual run's existing directory independently**. The
tool previously looked only in one `--logs-dir`, so both `meter` and `audit`
could misleadingly show `MISSING` when they existed elsewhere:

```bash
python scripts/diagnose_llm_dispatch_idle.py \
  --meter-logs-dir "<actual ctx.meter_dir/logs>" \
  --load-logs-dir "<actual ctx.PGMSubDir/logs>" \
  --audit-logs-dir "<actual ctx.PGMSubDir/logs>" --human
```

**Each override is a directory root:** meter contains `loadmeter_*.json`,
load contains `base_url_load.json`, and audit contains a *subdirectory*
`llm_call_audit` with `llm_call_audit_*.csv`. Do not pass the CSV folder
directly to `--audit-logs-dir`. Any unspecified source continues using
`--logs-dir` (default `./logs`). The three flags can be supplied to the
Windows `.bat` launcher as well; it forwards all arguments.

Machine JSON includes fixed `source_directory_selection` values
(`SHARED` or `EXPLICIT`) for each source and
`cross_source_run_identity: NOT_VERIFIED`. The human report prints the
same selection and the warning that source files may come from different
runs. **No paths, run IDs or endpoints are printed.** A missing, corrupt,
unsafe, or unavailable override affects *only that source's* status;
other readable sources remain visible. An observation is not authenticated
run correlation; combining arbitrary directories cannot establish which
Worker or GPU processed a particular queue item, nor prove root cause.

All reads remain bounded, file/dir symlink checks remain in effect, and
the tool performs no Queue/GPU/LLM/API actions or file writes. Review the
operator-owned run's actual folder locations locally; the tool deliberately
does **not** guess those locations or crawl the filesystem.

### Consumer／Worker Quality 異常的唯讀摘要（Issue #302，Phase 2）

在既有 `--audit-logs-dir`（或共用 `--logs-dir`）之下，診斷器會先定位最新的
`llm_call_audit/llm_call_audit_*.csv`，再只讀取**同名後綴**的
`llm_call_audit/processing_quality_events_*.jsonl`。
這是現有 Writer 的命名慣例；檔名配對**不能證明**同一個真實 Run。

額外 JSON 欄位 `sources.quality` 僅包含現有 Allowlist 中固定的 run-scope
Consumer、Row Merger、Producer、Stage、Worker 異常事件數（含固定 code 計數）及
有效時間區間，沒有 raw `run_id`、私有 document／slice ID、文字訊息或事件內文。
`archive_coverage=ACTIVE_GENERATION_ONLY` 表示**只看目前活動檔**；
歷史封存、已輪替檔案沒有計入，不能當成整次任務的總故障數、唯一文件數或真正根因。
GUI 既有聚合的歷史計數可能因此不同，請勿直接比較或相加。

任何 Quality 檔缺失、截斷、符號連結、非法 schema、時間或事件碼都獨立回報
固定 `MISSING`／`INCOMPLETE`／`UNSAFE_PATH`／`SCHEMA_MISMATCH` 等狀態，
不返回部分計數，也**不會掩蓋**另外三個 Meter／Load／Audit 來源已觀察到的證據。
如果 `sources.quality.status=OBSERVED` 且統計為 0，只代表所選目前檔案及
回溯窗口沒有看見列在 Allowlist 的事件，不代表執行健康或 GPU 忙碌。

範例：

```bash
python scripts/diagnose_llm_dispatch_idle.py --audit-logs-dir "<actual ctx.PGMSubDir/logs>" --human
```

這個 Phase 2 一樣只讀既有受控本機檔案，不產生新的 Quality JSONL、
不呼叫 LLM、沒有 GUI 或 Queue 寫入，也不嘗試猜測磁碟上的其他 Run 目錄。

For repeated **foreground** sampling while a batch runs:
    python scripts/diagnose_llm_dispatch_idle.py --logs-dir <runtime_logs_directory> --samples 12 --interval-seconds 30

The Python CLI prints one sanitized JSON object per sample by default;
`--human` prints a Traditional Chinese metadata-only summary per sample. It does not run a
background service, automatically save a file, edit job state or access
LLM/ES/SQL/GPU APIs. Only bounded existing metadata is examined:
latest loadmeter_*.json, base_url_load.json, latest
llm_call_audit/llm_call_audit_*.csv. The audit records *completed* local
Worker calls, not uncompleted in-flight requests. The meter, LB lease file
and CSV do not share an authenticated common run identity, and newest
modification times do not prove they belong to the same batch.

Limits: 4 MiB per JSON, 16 MiB audit CSV, 512 directory entries,
30000 audit rows, 64 endpoints, 4096 leases per endpoint; no symlinks /
reparse-point files, and changed-during-read snapshots are rejected.
Legacy timestamps without UTC offset are INCOMPLETE. The CSV reader also
requires a terminated physical record, strict CSV quoting and complete
column shape; interrupted append rows return INCOMPLETE without silently
counting a completed call. Error paths use
fixed codes only; URLs, endpoint IPs, paths, PKs, prompts, private run IDs,
raw provider errors and credentials never appear in stdout. Endpoint_01
labels are transient and are NOT actual GPU IDs or proof of an active request.

Interpret OBSERVED_NOT_PROVEN as a snapshot observation, not a passing
deployment or confirmed utilization. Pending/running/lease/audit signals
are candidate explanations only. Compare multiple samples with operator
nvidia-smi and Ollama measurements outside this tool before attributing
idle GPUs to batch barriers, stale leases or HTTP timeouts.

The endpoint load balancer tracks only requests assigned by its Worker.
Lock-timeout random fallback carries no persisted lease and cannot release
another Worker's claim. A late release never removes a replacement claim.
During an actual blocking `CallLLMAPI` invocation, a short-lived per-Worker
keeper now refreshes an existing, still-valid lease using the same lock.
It stops before final release and never creates a missing lease. Refresh
normally occurs every 100 seconds for the default 300-second lease, but
stops after 1200 seconds to avoid renewing a permanently stuck request.
Lock timeout/read failure or expiry may still leave inaccurate load counts.
**An HTTP call in flight is not proof of GPU computation.**

This diagnostic never frees lease files, modifies cache, changes limits,
retries Queue work, restarts workers or writes to SQL/ES. Real operator
acceptance, safe restart and independent sink readback remain Issue #266.
Focused synthetic test suite:
tests/prompt_pipeline/test_llm_dispatch_idle_diagnostic.py.
