# Stored multidimensional-event time audit (read-only, Issue #293 phase A)

The current ES rerun policy accepts operator-configured `required_output_checks`.
A rule requiring `Event_Timeline.time_iso` with `min_valid_count: 1`
will reject a legitimately empty `Event_Timeline: []`, even when
`Event.time_iso` is a trustworthy date. PR #300 deliberately preserved
existing policy semantics. **This audit does not silently change that policy.**

## Input / usage

From an approved local checkout, export only the **already persisted**
Elasticsearch document `_source` values (or equivalent source documents)
to a private newline-delimited JSON file. Export is a separate,
operator-controlled read-only operation; this tool does not perform it.
Keep source exports on a protected local disk: they may contain confidential
news, source identifiers and LLM responses.

Each line must be one JSON object with either
`{"_source":{"multidim_event_json":[...]}}` or
`{"multidim_event_json":[...]}`. A single nested article object also
works for legacy data; multiple article blocks are evaluated conservatively.

Windows:
```bat
python scripts/audit_multidim_event_time.py --input-ndjson "D:\\private\\es_source_export.jsonl" --human
```

Linux:
```bash
python scripts/audit_multidim_event_time.py --input-ndjson "/private/es_source_export.jsonl" --human
```

Default stdout is one sanitized JSON aggregate. The `--human` option
prints fixed Traditional Chinese labels. It never prints document IDs,
source paths, timestamps, event dates, original text, provider endpoint,
or exception text.

Input is capped at 16 MiB, 20,000 physical NDJSON lines and 512 KiB per
line. Invalid UTF-8, malformed JSON, truncated final line, unsafe symlink
or changed file metadata fail closed with `UNAVAILABLE`, without partial
counts. This is a non-atomic and unauthenticated file snapshot, not a
malicious-writer-safe audit. Use a stopped, stable exported file.

## Interpretation

`EVENT_DATE_EMPTY_TIMELINE` marks a **candidate false rerun** for the
specific old policy requiring at least one valid Timeline date. It means
the existing output profile's time-field validation accepts at least one
Event time and all Timeline arrays were explicitly empty. It does **not**
prove date correctness against the original article, ES sink acceptance,
or that the currently effective config actually contains that old rule.

`NO_RELIABLE_DATE` means no output date has been validated by this
audit; it does not prove that the original article is undated. It should
**not** cause automatic infinite reruns or fabricated dates.

`INVALID_TIME_FIELDS` and `UNVERIFIED_STRUCTURE` mean further investigation
is warranted; neither status authorizes overwrite or repair.
The audit checks existing Event / Timeline `time_iso`, `time_precision`
and `time_raw` using the existing ES output profile's field validator,
on copies. It is not full event_ids/source-evidence consistency validation,
a substitute for a real full Output Profile check, or a comparison with
current model fingerprint/metadata.

## Safe next steps

1. Record the aggregate count from a genuinely representative private
   export of already stored outputs; no ID/prompt data need be shared.
2. Separately inspect the **effective** ES rerun config, including the
   operator-private connection profile; confirm whether Timeline is still
   hard-required, and whether `pipeline_hash`, `force_since` or model
   fingerprints independently trigger reprocessing.
3. Design and test the new grouped Event/Timeline quality policy under
   Issue #293, allowing explicit unknown dates without inventing Timeline
   entries, while preserving opt-in force-rerun/overwrite.
4. Only with independent authorization should real ES data be rewritten.

Hosted CI verifies synthetic/temporary NDJSON inputs and direct Python
entrypoints on Linux and Windows 3.10/3.11. No live ES or LLM operation occurs.
