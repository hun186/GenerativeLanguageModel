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

## Optional hypothetical policy preview (phase B, no runtime change)

To compare only one **hypothetical** historical rule requiring a valid
`Event_Timeline.time_iso` (`min_valid_count: 1`) against a proposed
*date-only* triage, add `--compare-timeline-min-1`:

```bat
python scripts/audit_multidim_event_time.py --input-ndjson "D:\\private\\es_source_export.jsonl" --human --compare-timeline-min-1
```

The original seven category counts remain unchanged. Additional aggregate
`time_rule_comparison` fields distinguish:

- `legacy_fail_but_proposed_date_present`: the hypothetical strict Timeline
  check rejects a structurally recognizable record although a validated
  Event or Timeline date exists. **Potential** false rerun, not proof.
- `legacy_fail_but_proposed_time_unknown`: the old check rejects a record
  with no validated date; **original article date is unverified**, so a
  future policy must not fabricate a date or keep retrying blindly.
- `legacy_time_rule_indeterminate`: malformed time or uncertain structure;
  neither historical nor proposed policy is labeled successful.
- `legacy_timeline_min_1_pass/fail`: the single isolated Timeline check
  only, never the entire active ES rerun or completion decision.

No current or private `required_output_checks`, execution fingerprint,
`pipeline_hash`, `force_since`, `stale_after_days`, source fidelity, or
writeback state is read or evaluated. This is an offline scenario, **not an
effective-config diff or authorization to skip**, and is only as reliable as
the privately exported, stable source documents. Other rerun reasons may
remain even if a time rule would pass. The CLI does not contact ES and writes
nothing. This PR explicitly makes no change to rerun policy.

Before any true rerun semantics change, separately verify the effective
operator configuration and confirm a sample against original sources and
sink readback. Preserve an explicit force-overwrite path and test both ES
pending policy variants before deployment.

## 2026-11-11 / Issue #293: Event-first temporal rerun rule (PR candidate)

Three ES multidimensional-event YAML examples now use
`path: multidim_event_json; validator: multidim_event_time` instead of
requiring a nonempty `Event_Timeline.time_iso`. The new shared Python
required-output validator reuses `classify_stored_document()` and the
existing writeback Output Profile time validation: every article block must
have a core Event, valid Event/Timeline time fields pass, and an explicit
`time_iso: null` with `time_precision: unknown` may pass without fabricating
a date or calling an LLM. An empty Timeline is valid. Missing Event, malformed
time and unverified structure fail. **This is structural/format acceptance,
not proof that the original article contains no recoverable date.**

This time rule alone cannot prevent independent `pipeline_hash`,
`force_if_missing_meta`, model/fingerprint or operator force reruns.
The three existing YAML test-mode hashes were deliberately preserved; verify
the *effective* private config before enabling against production data. Existing
legacy `validator: date` remains unchanged for other tasks.

Status: source-only change proposed; no private Elasticsearch query, rewrite,
production replay or physical Windows acceptance was performed.

### Python sample config parity and repair-attempt budget (future)

The earlier phase updated five duplicated `akconfig_es_*.py.example`
files, but the later consolidation removes all seven per-index ES examples.
The only remaining ES Python example is `config_es/connection.py.example`.
It documents the Event-first check with `rerun.enable=False` by default,
avoiding automatic replay based on old copied `force_since` or hash settings.
Operator-owned private `.py` files and every task YAML path remain unchanged.
See `docs/usage/es_connection_profile_examples.md`.

An automatic maximum (suggested: two quality repair runs after the initial
extraction) is NOT implemented by this PR. A durable per-document/output-policy
ledger is required, since failed validation can prevent ES output writeback.
Increment only after a completed extraction with a quality rejection, never
on discovery/recheck, network retries or incomplete execution. An idempotent
concurrent claim/finalize, review state, and explicit operator reset require
independent testing. Exhaustion must not mark an invalid output as fresh.

The Event-first guard additionally requires nonblank, distinct
`Event.event_id` values per block. Missing `time_iso` with missing
`time_raw` is accepted only when precision explicitly says `unknown`;
a non-unknown precision can still represent a partial time if a nonempty
`time_raw` is preserved. This is a conservative validation rule, not
source-language inference.

## Public ES Python template consolidation

Seven duplicate `config_es/akconfig_es_*.py.example` files were consolidated
into one canonical `config_es/connection.py.example`, with per-index legacy
file mappings documented in `docs/usage/es_connection_profile_examples.md`.
Legacy `es_config_file` YAML references and operator-owned private/root
`.py` files were not changed. No implicit date-rule rerun or ES writes.
