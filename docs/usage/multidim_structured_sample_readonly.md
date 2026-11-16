# MultiDim structured-output-only random sample (operator GET-only)

## Why this exists

A random sample of *all* `news_test` documents mixes articles already
containing `multidim_event_json` with ones that have not been extracted.
That can overstate `UNVERIFIED_STRUCTURE` and incorrectly suggest a
quality Rerun is required. This tool independently counts the full index
and the documents matching a nested `multidim_event_json` query, then
samples **only the latter**. The nested-query count is **not** a perfect
inventory of all nonempty `_source` output representations; explain
that denominator as "nested indexed candidates", not "all processed docs".

## Operator command (Windows, within a trusted GLM checkout)

```bat
python scripts/audit_multidim_structured_sample_readonly.py --run --url "https://es.example.invalid:9200" --ca-cert "czjLLM/config_es/certs/http_ca.crt" --sample-size 150
```

Replace the reserved `es.example.invalid` name locally with the actual
ES HTTPS origin, never commit the actual endpoint. The operator is
prompted for username and a hidden password. Do not put credentials on
the command line. If the previously verified CA is trusted but the
locally confirmed **old IP SAN** is wrong, `--allow-ip-san-mismatch`
permits **diagnostic-only** observation without disabling CA/expiry
validation. Its status is `OBSERVED_WITH_TLS_EXCEPTION`, not PASS.
Normal verification is required for production release acceptance.

Without `--run` this command performs no network or credential input
and returns `NOT_TESTED`.

## Exact read scope

The tool performs at most **three** HTTPS GET requests with fixed index
and limited response sizes:

1. `/news_test/_search`: size 0, exact count of all documents.
2. `/news_test/_search`: size 0, exact count of **nested** MultiDim
   candidate documents (nested `match_all`).
3. `/news_test/_search`: seeded `random_score` sample of at most 300
   candidates; response `_source` restricted to `multidim_event_json`.

All three queries are GET URI-encoded JSON with a 3072-character request
path bound, no redirects, no scroll/PIT, no ES writes/Mapping update,
no bulk, no LLM, no rerun. The input can include private article text
in **local process memory** for strict Output Profile validation,
but it is never exported, written to disk or printed. Results contain
only fixed status labels, counts and diagnostic codes: no endpoint,
credentials, document IDs, event IDs, dates, text or raw query response.

A sample remains non-atomic and exploratory: ES updates between the
three requests can cause `INDEX_COUNTS_CHANGED`; this does not authorize
any automatic retry or write. Use off-peak read-only access.

## Interpret categories carefully

- `profile_counts.PROFILE_ACCEPTED_NO_EVENTS` means the current
  Output Profile accepts a structural no-Event result. It does **not**
  prove the original article is irrelevant.
- `profile_accepted_no_events_and_task_guard_eligible` is an
  **isolated** task-owned `multidim_event_time` acceptance comparison
  with `allow_empty_events: true`, not actual effective runtime pending.
- `time_counts.UNVERIFIED_STRUCTURE` can coexist with
  `profile_counts.PROFILE_REJECTED`, but these counts have different
  semantics; they cannot be summed as independent errors.
- `profile_counts.OUTPUT_ABSENT` in the nested candidate sample is
  an anomaly that should be examined before interpretation; absent
  output outside this nested sample is **not included** in the
  profile breakdown.
- A dated Event with empty Timeline remains acceptable, subject to
  the full Output Profile and SRAF's evidence/date checks.
- `effective_runtime_rerun=NOT_EVALUATED` means the tool has not
  considered task-private YAML/Python policy, pipeline fingerprint,
  force_since, model version, or any production launch conditions.

This does not establish original-source fidelity, full-index rerun
counts, actual SRAF recall, correct article coverage, Chinese analyzer
quality or a safe deployment decision. Prefer actual source comparison
and separately checked effective job policy before any operations.
