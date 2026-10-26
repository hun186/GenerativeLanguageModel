# Offline Quality Report — optional temporary SQLite identity spill

The existing report remains unchanged by default. For a **large single-run or
history JSONL report**, opt into a temporary disk-backed identity index:

```bash
python -m czjLLM.cli_tools.processing_quality_report \
  --audit-path /path/to/llm_call_audit_<run_id>.csv --disk-backed
python -m czjLLM.cli_tools.processing_quality_report \
  --audit-dir /path/to/logs --limit 20 --disk-backed --output quality-report.json
```

## Contract and boundaries

- `--disk-backed` is **opt-in**; without it, the original in-memory report,
  counters, JSON shape (`report_version=1`), archive SHA-256 validation and
  parsing behavior are unchanged. Run-history is still aggregated independently
  for each run.
- The temporary index contains the **exact raw event IDs, SHA-256 event
  signatures, and document identity sets** required to preserve duplicate-ID
  semantics, conflicting duplicate detection, and reject→confirmed recovery.
  It is created under an OS-managed private temporary directory with a
  mode-0600 SQLite file, then removed on successful reports and exceptions.
  The generated JSON report contains aggregate counts, not raw identities.
- **Security:** the temporary index has sensitive identifiers while the report
  executes. Run only on a trusted local disk/OS account with sufficient free
  space. OS crash or forced termination can leave remnants; the operating
  system's backup/swap/forensic storage behavior is outside this cleanup
  guarantee. Do not use untrusted or shared temporary storage.
- SQLite reduces the number of identities held in Python sets/maps but this
  **does not guarantee any absolute RSS bound**, eliminate large JSON-line
  allocations, or provide constant-time performance. The default offline reader
  is still uncapped; the GUI safety budgets from PR #233 remain separate.
- This is **not a persistent checkpoint**, safe archive retirement mechanism,
  archival authentication, an automatic rotation/deletion service, or a way to
  resume after a crash. It does not authorize rotating files while producers or
  GUI readers are running. SQLite storage/availability errors fail closed.
- A real-provider, Windows/Tk resource-profile, and live ES independent
  writeback/readback acceptance remain separate operator validation tasks.

### Acceptance

The focused regression suite compares default and disk-backed summaries over
real sealed archive+active JSONL, document recovery, corrupt/conflicting
duplicates, partial tails, CLI JSON output, history, and SQLite cleanup. Hosted
Linux `offline-e2e` must pass these tests and a formal exact-head Codex review
must report zero unresolved P1/P2 before merge. Explicit user permission remains
required for every Merge.
