# Processing Quality: offline per-run reports (PR after #218)

This tool reads the **existing** logs/llm_call_audit/processing_quality_events_<run_id>.jsonl.
It does not call LLM/Ollama, a database, or network, and does not generate another audit stream.
It does not modify either the original llm_call_audit CSV/XLSX or the quality JSONL.

Use one specific run (the matching CSV need not itself exist yet, as long as its JSONL exists):

    python -m czjLLM.cli_tools.processing_quality_report --audit-path logs/llm_call_audit/llm_call_audit_20261020-123456-123.csv

List at most 20 latest quality run files from the same directory:

    python -m czjLLM.cli_tools.processing_quality_report --audit-dir logs/llm_call_audit --limit 20

Write a separate **summary JSON**, atomically:

    python -m czjLLM.cli_tools.processing_quality_report --audit-dir logs/llm_call_audit --output quality_summary.json

The percentages and counters reuse QualityAccumulator, including de-duplication and recovered-schema semantics; source event records/document IDs are not exported. Unknown denominators show null, not 0%. Each denominator under 30 adds an **advisory only** (not a statistical pass/fail gate). The reports never combine numerators/denominators across runs.

A partial trailing JSONL record is ignored until complete, and reported as incomplete_or_concurrent_append; the file may be actively appended during inspection. Malformed complete UTF-8/JSON lines are excluded from denominators but counted in `skipped_corrupt_complete_lines`; the state becomes `degraded_corrupt_lines` even when other valid events exist. This is a completeness warning, not a forensic reconstruction of damaged content. Invalid-schema JSON records and duplicate event IDs continue to use the existing reader policy.

Confirmed writeback applies only to explicit Sink acknowledgement (currently ES bulk, not ES read-after-refresh). A missing confirmation for Excel/CSV is **unknown**, not failed. A document-schema pending percentage only covers observed, decided documents, not all scheduled documents.

The user must still perform a small real Windows + LLM + ES acceptance run for merged PR #218. Keep this new report PR unmerged while using the pinned #218 merge commit for that acceptance.
