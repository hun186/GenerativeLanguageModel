# JSON list completeness validation (2026-11-08)

## Problem

The long-standing `robust_merge_json_lists` batch helper intentionally
skips malformed array segments if local `repair_json` cannot recover a list.
The returned JSON can therefore be `[]` or a valid-looking prefix even when
the original model output contained additional unparseable segments.

For **standalone result validation**, presenting that partial JSON as complete
is unsafe. For example, `PromptResultHandler.validate_json` previously
accepted an arbitrary plain-text response as `[]`, or accepted a valid first
array after a second array failed repair.

## Contract and compatibility

The existing `robust_merge_json_lists(raw)` and
`combine_json_return(raw)` retain their tolerant default results.
A new **keyword-only** `require_complete=True` on those helpers opts into
fail-closed validation:

- `JSON_ARRAY_SEGMENT_MISSING`: no complete array was present.
- `JSON_ARRAY_SEGMENT_SKIPPED`: one or more array segments failed JSON parsing
  and local repair, or repaired into a non-list result.
- `JSON_ARRAY_SEGMENT_INCOMPLETE`: the existing strict scanner found an
  unterminated array or quoted string (always raised on this combine path).

`PromptResultHandler.validate_json` now opts into `require_complete=True`
only if the original strict `json.loads` failed. It returns `(False, "")`
for these cases. `parse_result` then retains the original cleaned text in
its existing `{"text": ...}` fallback instead of claiming empty or
partially successful JSON.

A valid `[]`, object, correctly concatenated multiple JSON arrays, or a
malformed array that local repair successfully restores to a list still
follows its existing successful path.

## Limitations

This enforces **syntactic array-segment completeness**, not source-to-output
semantic coverage, model factual correctness, or SQL/ES durable writeback.
The opt-in check cannot determine whether extra non-array prose outside
complete arrays should count as an output requirement. Legacy batch result
combiners remain tolerant and can still skip malformed segments; changing
their default is a separate, higher-impact data-integrity policy.

Offline regression `tests/test_json_merge_complete_validation.py` covers
missing/partial/repaired/incomplete/non-list scenarios, legacy default
compatibility and privacy of local diagnostic output. Hosted CI is the
only verification for this PR until operator-controlled physical
Windows/Linux runs and independent sink readback (Issue #266).
