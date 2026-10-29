# Processing Quality P2 — offline LLM call failure taxonomy

This *separate* read-only report classifies **existing** per-run
`logs/llm_call_audit/llm_call_audit_<run_id>.csv` entries with `ok=NO`.
It requires no local model, Elasticsearch, SQL Server, or network access.

```bash
python -m czjLLM.cli_tools.llm_failure_report --audit-path logs/llm_call_audit/llm_call_audit_20261022-123456-1.csv
python -m czjLLM.cli_tools.llm_failure_report --audit-dir logs/llm_call_audit --limit 20
python -m czjLLM.cli_tools.llm_failure_report --audit-dir logs/llm_call_audit --output failure_summary.json
```

The optional `--output` JSON is a **separate** aggregate report, never an
audit file or sealed quality archive ledger. Regardless of the source audit
directory, the CLI rejects `processing_quality_events_*.jsonl.manifest.json`
destination names (including nonexistent reservations and case variants on
Windows) before parsing source CSV. Within the source audit directory, it also
reserves `llm_call_audit_*` and `processing_quality_events_*` filenames.
A regular `failure_summary.json` elsewhere remains supported and atomically
replaceable. Output symlink aliases are refused. These guards prevent ordinary
CLI mistakes but are not an authenticated archive or a race-free guarantee
against malicious directory replacement.

## Optional observed local-time window

The producer currently writes its CSV `timestamp` as **local, timezone-naive**
`YYYY-MM-DDTHH:MM:SS` (`datetime.now().isoformat(timespec="seconds")`).
Use `--since` (inclusive) and/or `--before` (exclusive) when the producing
host's local clock is known, for example:

```bash
python -m czjLLM.cli_tools.llm_failure_report --audit-path logs/llm_call_audit/llm_call_audit_20261022-123456-1.csv --since 2026-10-28T10:00:00 --before 2026-10-28T12:00:00
python -m czjLLM.cli_tools.llm_failure_report --audit-dir logs/llm_call_audit --since 2026-10-28T10:00:00 --before 2026-10-28T12:00:00
```

Only events in `[since, before)` contribute to **that run's** existing
`observed_call_attempts`, `failed_call_pct` and category counts. With a
filter, the existing `report_version=1` JSON adds a fixed `time_window`
object (`since`, `before`, `bounds`, `clock`) and each run adds
`excluded_by_time_window`; without either flag, the JSON shape and legacy
behavior remain unchanged. Empty selected windows show null failure
percentage, not 0%. History still counts and lists the same bounded audit
files as before, without pooling counters from unrelated runs.

**Completeness rule:** a filtered report requires one `timestamp` column
and valid local-second timestamps for **every** CSV row, even rows outside the
requested window. Undated/malformed-width rows fail closed rather than being
guessed into or silently excluded from the denominator. The existing 16 MiB
per-file, 64 MiB history, file-generation and no-follow guards still apply.
Input files are read-only; errors remain generic and omit paths/secrets.

UTC offsets, `Z`, fractional seconds, date-only values and reversed/empty
intervals are rejected. **Do not compare timestamps produced on different
hosts/time zones as one absolute chronology.** The report does not perform a
timezone conversion, infer retry identities, or assert unique document
failures. Physical Windows/Ollama/ES acceptance still requires separate
operator verification.

## Meaning and coverage limits

- **Denominator:** individual logged LLM call attempts with an explicit
  `ok=YES` or `ok=NO`, not distinct documents, not scheduled rows,
  not the full production worker/pipeline error population.
- The failure percentage has denominator `observed_call_attempts`.
  Missing, unexpected, or invalid outcome cells are reported separately,
  **never treated as success or failure**. A zero denominator remains null.
- Only `ok=NO` rows are classified using conservative error-text patterns:
  `rate_limit`, `timeout`, `context_budget`, `transport`,
  `json_postprocessing`, or `unclassified`. These labels are heuristic
  request-error categories, **not** a diagnosis that a document failed or
  an assertion that the model generated invalid JSON. A post-response local
  exception may produce `ok=NO` while preserving API token usage.
- Stage orchestration crashes that did not generate an LLM audit row,
  retries not logged as separate requests, final document schemas, and
  sink-specific confirmation must be evaluated using their own sources.
  The independent JSONL Processing Quality report covers slice JSON
  validation/repair and explicitly confirmed ES writeback decisions.
  Do not add the two reports' percentages or assume they share units.
- The report contains only fixed category counters and *no source filenames*:
  it **never outputs raw errors, prompts, response text, task IDs,
  document IDs, URLs, or credentials**. It does not rewrite the CSV or XLSX.
- CSV snapshots must be complete UTF-8 with a newline-terminated last
  record, strict required headers and a maximum size of 16 MiB each.
  History selects at most 100 newest named CSVs, with a combined 64 MiB
  budget and bounded directory discovery. Exceeding any bound fails
  explicitly instead of displaying misleading zero counts.
- A report is observational; live CSV appends and Windows/LLM/ES
  acceptance remain independent verification. An audit row cannot establish
  completed stage processing, successful ES readback or document delivery.

This P2 stage intentionally does **not** add an exception body to the
processing-quality JSONL and does not change runtime LLM/ES flow.

The snapshot opener uses no-follow semantics where supported, plus opened-file
identity checks. Blank CSV records are counted as degraded/invalid, not silently
dropped. History size is verified against the combined budget after each
opened snapshot; source filenames and free-form error strings are never emitted.

Directory scopes are validated with no-follow metadata for every path
component, rejecting Windows junction/reparse roots and symlink aliases
rather than trusting `is_symlink()` alone.

The audit reader also captures all ancestor directory identities and
revalidates them immediately after opening and again after reading, so a
parent switched to a new symlink/junction during the operation invalidates
the snapshot. The report is observational, not a forensic integrity proof
against an adversary able to perform undetectable rapid ABA replacements.

The history-scoped inventory snapshots the originally approved directory
identity and revalidates it after discovery, before and after each selected
CSV read, and before publishing results. Replacing the root with a different
*ordinary directory* is therefore also rejected instead of silently
returning substituted audit data.

Handled automatic JSON-repair failures after an LLM request now persist
a fixed JSON_POSTPROCESSING_FAILED audit marker, without raw JSON or exception
text, so they can be counted as json_postprocessing rather than unclassified.
Legacy audit rows are unchanged and cannot be retroactively reclassified.
On POSIX, O_NONBLOCK prevents a substituted FIFO from blocking the reader;
the opened file must still be a verified regular file.

The bounded report uses a self-contained CSV record parser supporting
producer-written quoting, escaped double quotes, embedded newlines and large
error fields. It does **not** access or modify Python's process-global
csv.field_size_limit(), even when other threads parse CSV concurrently.
Malformed quoted-field syntax fails closed; empty physical records are
counted as invalid observations.

The CSV parser avoids per-character list buffering for large producer
fields: normal fields are source slices, while quoted fields write
contiguous spans into a StringIO buffer. This keeps memory proportional
to the bounded audit input instead of multiplying allocations for each
character. A multi-megabyte quoted error regression tracks peak memory.

Every CSV row is bounded by the already-validated header width before any
extra field is buffered. Header discovery also has a 128-field hard cap,
comfortably above the audit producer schema. Malformed comma-flood rows
fail explicitly and cannot multiply memory usage through millions of
empty per-field Python objects.
