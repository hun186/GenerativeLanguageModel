# Processing Quality P2 — offline LLM call failure taxonomy

This *separate* read-only report classifies **existing** per-run
`logs/llm_call_audit/llm_call_audit_<run_id>.csv` entries with `ok=NO`.
It requires no local model, Elasticsearch, SQL Server, or network access.

```bash
python -m czjLLM.cli_tools.llm_failure_report --audit-path logs/llm_call_audit/llm_call_audit_20261022-123456-1.csv
python -m czjLLM.cli_tools.llm_failure_report --audit-dir logs/llm_call_audit --limit 20
python -m czjLLM.cli_tools.llm_failure_report --audit-dir logs/llm_call_audit --output failure_summary.json
```

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
