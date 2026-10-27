# Quality JSONL: offline exact-report performance and parity probe

The existing single-run quality report has two supported modes: default
in-memory, and opt-in private temporary SQLite identity storage with
`--disk-backed`. To **measure a stopped, real run** before making performance
claims, run the independent benchmark command:

```bash
python -m czjLLM.cli_tools.processing_quality_benchmark \
  --audit-path /trusted/logs/llm_call_audit_<run_id>.csv \
  --repetitions 2 --timeout 300
```

This emits a JSON summary to stdout, containing no run identifiers, raw event
IDs, document IDs, prompts, exception text, filesystem paths, or credentials.
It uses the existing report code to verify archived SHA256 integrity and
degraded/corrupt line status. **Every run's source files must be stable:
stop producers and maintenance rotation before benchmarking.**

## Interpretation

- Samples run as **fresh child Python processes**, one mode per process,
  alternating modes to somewhat reduce page-cache order bias. Workers receive
  input paths via stdin, not process command-line arguments, and report only
  aggregate measurements and a SHA256 digest of the complete canonical
  report. A digest mismatch across any sample aborts instead of returning
  potentially misleading comparisons.
- `median_seconds` measures the actual report call, **excluding process
  startup and imports** but including `tracemalloc` overhead. Do not interpret
  it as unaided production throughput or a strict service SLA.
- `median_peak_traced_python_bytes` is Python allocations traced since the
  start of the report, **not total RSS** or database pages. When supported,
  `median_peak_process_rss_bytes` uses OS high-water RSS on Linux/macOS;
  on Windows it calls native PSAPI `GetProcessMemoryInfo` and reads
  `PROCESS_MEMORY_COUNTERS.PeakWorkingSetSize` (historical peak resident
  **working set**, not private committed memory or a hard RAM ceiling).
  It includes interpreter/import baseline, so compare only modes on the same
  host, Python build and workload; never compare peaks across platforms.
  If the OS call fails, the field remains `null` rather than an inferred
  zero. Simulated Windows API regressions run in Linux CI; real Windows
  native/GUI physical acceptance still requires an operator run.
- `median_sqlite_main_db_final_bytes` is the SQLite main temporary index
  size just before normal cleanup, **not cumulative bytes written, WAL,
  journal, swap, file-system cache, or total physical disk I/O**. It is `null`
  for in-memory samples. This figure is a disk-capacity indicator, not a
  throughput counter.
- Repetitions are 1..5 and subprocess timeout is 1..3600 seconds. At least
  2–3 samples and multiple typical *real* run sizes should be collected
  before deciding whether the SQLite mode actually reduces pressure enough
  to justify its slower disk operations. No automatic mode selection is added.

## Safety and scope

The benchmark never writes to existing audit CSV, JSONL, archive shards or
manifests and does not create a persistent checkpoint. The existing SQLite
mode creates a **private OS temporary identity index** containing raw
identifiers while each worker runs, deleting it during ordinary cleanup.
Use only a trusted local machine with sufficient private temporary storage:
an OS crash or forced kill can leave remnants; swap/backups are outside the
application's deletion guarantee.

The benchmark also captures a bounded **read-only metadata snapshot** of the
canonical active JSONL, numbered archived shards, and optional manifest before
and after every isolated sample. New/removed shards, changed file identity,
size, modification or change times abort even when the complete report SHA-256
happens to match (for example, appending an invalid complete JSONL line whose
aggregate metrics do not change). A run with no quality stream does not
produce fake performance measurements; symlinked input files are rejected.

This **is not** an atomic file snapshot, an authenticated content hash, a lock,
or a protection against malicious rewrites that restore file metadata. Stop all
producers and maintenance rotation during measurement. On change, the CLI
fails with a generic, path-free error. It never outputs filenames, raw IDs or
private paths.

No live Ollama, Windows GUI visual acceptance, **real** Windows PSAPI
execution acceptance, ES independent readback, automatic archived-file
deletion or safe online rotation is implied by Linux CI on this probe. Merge only after latest-head Hosted Linux tests and formal Codex
review, with explicit user authorization.
