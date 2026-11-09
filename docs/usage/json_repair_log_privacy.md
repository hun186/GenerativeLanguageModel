# JSON repair console privacy: fixed diagnostics only

The legacy `czjLLM.utilities.json_combining` helper participates in
offline LLM JSON combining. Repair-failure diagnostics must not copy
original model output into a console or captured batch log.

Previously, failure branches included the first 200 characters of a
malformed segment, a full combined JSON result, or a repaired object,
and copied exception text. These strings may include source articles,
private model output or credentials in unexpected exception messages.

The helper now emits fixed, payload-free codes instead:

- `[JSON-COMBINE] decode_failed; attempting_local_repair`
- `[JSON-COMBINE] repaired_segment_accepted`
- `[JSON-COMBINE] repair_failed_segment_skipped`
- `[JSON-COMBINE] combined_decode_failed; attempting_local_repair`
- `[JSON-COMBINE] repaired_item_shape_invalid`
- `[JSON-COMBINE] combined_postprocess_failed`
- `[JSON-COMBINE] combined_repair_succeeded`

Only **console logging** changes. Existing recovery behavior and
`combine_json_return` return values are intentionally unchanged;
this is not a claim of JSON validity improvement, lossless repair,
or SQL/ES sink confirmation. A repair that cannot restore valid
content may still be skipped by the historical combiner. Treat
that as a separate data-integrity policy decision, not as a
log-redaction patch.

Offline `tests/test_json_repair_log_redaction.py` forces
malformed input, failing repair, shape failure and successful repair,
and checks that neither original content nor exception text appears
on standard output. Hosted Linux CI runs the new test.
Existing older audit CSV/files may contain raw error text and are
**not** retroactively redacted; restrict their file access.

## Row Merger combine-preparation warning boundary (2026-11-09)

The Row Merger's `combine_api_finished_item()` preparation retry can raise
an exception whose message contains raw document content or private model
output. Its current and legacy fallback warning branches now emit only the
fixed `ROW_MERGER_PREPARE_RETRY` code; neither raw exception strings nor
per-document PKs are included in those warnings. The underlying retry and
run-scoped quality incident semantics are unchanged; no Queue, LLM,
JSON validation or SQL/ES persistence operation changes.

The offline `test_row_merger_combine_prepare_retry_is_audited_then_recovers`
regression checks warning privacy and preserves retry-to-writeback behavior.
This narrow fix does **not** assert unrelated Row Merger diagnostics or
legacy artifacts are payload-free and does not clean historic logs.

## Row Merger terminal schema-rejection console diagnostics (2026-11-09)

A completed document can fail Row Merger's terminal schema validation
with an exception that contains model output, document identifiers or
local filesystem paths. The terminal rejection branch now emits only
fixed warning codes: `ROW_MERGER_SCHEMA_REJECTED_PENDING`, with
`AUDIT_RECORDED` or `AUDIT_UNAVAILABLE`, plus distinct fixed codes for
failed row-state release, adjustment logging and quality-event audit.
These warning calls do not contain the exception class, message, PK or
adjustment path.

The private `record_adjustment` call still receives the original error,
PK and combined path so the operator can investigate without losing
evidence; these records must not be published as public logs. This is
console redaction only, not changed schema classification, retry or
SQL/ES writeback behavior. A parametrized offline regression exercises
normal rejection and injected state/audit/quality helper failures and
asserts privacy and original pending semantics. Other Row Merger
warnings, old logs and persisted private audits remain out of scope.
