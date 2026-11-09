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
