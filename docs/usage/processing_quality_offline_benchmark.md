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
  `median_peak_process_rss_bytes` is OS high-water RSS (Linux/macOS);
  it includes Python runtime/library baseline, so compare only on the same
  host/build and matching workload. On unsupported systems it is `null`.
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

Source-file changes between samples are detected whenever they alter the
canonical report digest. This is not a cryptographic source-generation lock:
stop all producers to avoid a concurrent append/rotation or a same-digest
rewrite. Benchmark failures emit generic sanitized messages; no source or
path-bearing exception text is printed.

No live Ollama, Windows GUI visual/physical RSS acceptance, ES independent
readback, automatic archived-file deletion or safe online rotation is implied
by this probe. Merge only after latest-head Hosted Linux tests and formal Codex
review, with explicit user authorization.
