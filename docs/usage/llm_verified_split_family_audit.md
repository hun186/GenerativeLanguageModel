# Verified split-intent family lineage in LLM call audit

After PR #248 established a bounded, **hash-verified** UUID4 on the
existing `_extract_slice_identity/splits/*.txt.json` journal, production
`PromptAPIPipeline.proc()` now reads
`verified_split_family_id(self.promptFile, self.content)` at its **existing
post-processing audit boundary** and forwards the result to
`log_llm_call(split_family_id=...)`. Newly created per-run CSVs and their
XLSX convenience exports append a trailing `split_family_id` column after
`call_llm_api_returned`.

A verified split family may connect a failed JSON parent and a direct child
(or a nested descendant) **only if the current prompt text matches the
persisted journal's canonical SHA256 evidence**. A parent that has just
created its durable split journal can be associated even after unlinking
its original RUNNING prompt. Changing child prompt text, lacking a journal
(or a valid UUID4), a malformed/legacy journal, an unrelated same-looking
basename, or encountering a symlinked journal namespace must yield **blank**.
New nonempty IDs are UUIDv4 lowercase 32 hex, never derived from names,
prompt content, error strings or endpoints, and require a Worker call ID.

## Boundary and limitations

- This is **explicit JSON split-intent ancestry** only. It is not an
  exhaustive source-document identity, general RUNNING→TODO requeue/retry,
  a provider HTTP request, an SDK retry, or durable evidence of completed
  split children. The split journal is not authenticated or race-free.
- No retry count, family failure/success rate, document denominator or
  provider acknowledgement is inferred. Existing `audit_record_id`,
  `worker_call_id`, `call_llm_api_returned`, final local `ok`, and
  read-only `llm_failure_report` report-v1 denominators are unchanged.
  The failure report does not expose this new ID.
- Four prior complete CSV header generations remain append-compatible;
  old running CSV files keep their **existing widths**. Their historical
  rows are not retroactively assigned ancestry. Unknown headers fail
  closed without rewriting source data.
- The audit column contains an opaque UUID or nothing; it contains no
  plaintext prompt, source row ID, error payload or URL. Existing legacy
  CSV fields have their original privacy/retention contracts.
- A Worker crash or audit persistence failure may leave no CSV row. The
  bounded journal lookup is observational: it does not create, change,
  repair or delete split journals, TODO, RUNNING, Success or sink data.

## Test and release gates

Real-file tests use source split installation and the actual Worker
`proc()` audit boundary with an injected local wrapper failure, then check
real CSV/XLSX IDs, mismatched digest rejection, unrelated rows, strict
UUIDv4 validation, four earlier header generations and unchanged offline
failure-report observed row counts. The test double is not a provider or
physical end-to-end validation. Require latest-head Hosted Linux
`offline-e2e` and formal Codex Review before merging. Windows/Tk/PSAPI,
live Ollama, actual ES/SQL independent readback and general retry
orchestration remain operator-gated. PR #231 stays isolated.
