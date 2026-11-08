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
