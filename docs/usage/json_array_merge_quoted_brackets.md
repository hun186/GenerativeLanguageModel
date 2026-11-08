# JSON multi-array merge: quoted-bracket safety (2026-11-08)

This is a **local parsing correctness** fix for the existing
`czjLLM.utilities.json_combining.robust_merge_json_lists` /
`combine_json_return` compatibility path. It is not an extra LLM request,
a schema repair policy, or a SQL/ES writeback change.

## Why it matters

A generated JSON string can legitimately contain `[` and `]` as **text**,
for example an event summary that quotes `"Policy [draft]"`. The old
`split_json_arrays` counted those characters as structural brackets and
could prematurely cut or splice valid JSON. The downstream repair fallback
could then be invoked on a formerly valid array, introducing unnecessary
local processing and possible altered content.

`robust_merge_json_lists` now calls the already existing
`split_json_arrays_safe`, which tracks quoted strings and `\\` escapes while
counting real nested arrays. The remainder of the combination flow,
`json.loads` and its existing `repair_json` fallback for balanced but
invalid syntax is unchanged. If the array scan ends mid-array or mid-string,
the combined-result path now raises fixed `JSON_ARRAY_SEGMENT_INCOMPLETE`
instead of quietly returning an empty/partial list. The public standalone
scanner's original tolerant default remains available for compatibility.
`PromptResultHandler.validate_json` treats that fixed failure as an invalid
JSON result, allowing `parse_result` to preserve the original text rather
than falsely accepting `[]`.
The public legacy `split_json_arrays` helper is retained for compatibility,
but is no longer used by this combination path.

## Evidence and scope

- Offline regression `tests/test_json_combining_brackets.py` proves that
  quoted literal brackets, embedded escaped quotes and backslashes, nested
  arrays, Chinese strings, multiple arrays and fenced JSON retain the
  exact parsed data and **do not call repair_json when already valid**.
- Verify the `combine_json_return` compatibility call, not just the
  low-level splitter. Balanced malformed arrays still use the existing local
  repair path; an **unterminated quoted array fails closed**, including after
  an otherwise valid prefix or before a valid later array. Do not silently
  accept a truncated/empty result as successful; arbitrary invalid JSON is
  not guaranteed repairable.
- Hosted Linux CI runs the focused suite plus the existing JSON slice-merge
  tests. Hosted Windows NTFS fixture jobs remain independent. Do not infer
  a real provider JSON validity percentage, token savings, or SQL/ES ACK
  from these deterministic regression tests.

Future model-vs-model JSON compliance comparisons require actual,
well-defined first-pass and repaired-response denominators; this fix alone
does not measure production model output quality.
