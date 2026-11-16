# Safe real-Index Mapping compatibility probe for MultiDim tasks

This probe is separate from the GLM general parallel-execution framework.
It compares the **actual** Elasticsearch `news_test` Mapping against the
task-scoped pinned `multidim_search_v1.json` contract.

## Operator usage (read-only)

From the GLM repository on the operator's trusted machine:

```bat
python scripts/audit_multidim_es_mapping_readonly.py --url "https://192.168.0.134:9001" --ca-cert "czjLLM/config_es/certs/http_ca.crt"
```

The operator is prompted for their Elasticsearch username and hidden
password. No credential is accepted in command-line arguments. The CA file
must exist. For the **previously confirmed, obsolete IP SAN** only,
`--allow-ip-san-mismatch` is an explicit local diagnostic option. It
skips hostname verification, **not** the certificate-chain check, and the
result is `OBSERVED_WITH_TLS_EXCEPTION`, never an unconditional PASS.

## What it does / does not do

The script performs exactly one bounded HTTPS **GET**
`/news_test/_mapping`. It forbids other URLs/paths, HTTP, redirects,
cross-index Mapping responses and oversized JSON responses. It compares
the current index's `nested` paths, scalar Mapping types, date formats
and the relevant dynamic policy with the v1 contract. It reports only
fixed, public contract field names and stable discrepancy reason codes;
it does not print the endpoint, original ES Mapping JSON, credentials,
article text, document IDs or ES source data.

Possible mapping results are `OBSERVED_MAPPING_COMPATIBLE`,
`OBSERVED_WITH_TLS_EXCEPTION`, `REVIEW_REQUIRED`, or `UNAVAILABLE`.
A date-format mismatch is **review required**, not automatic evidence
of semantic incompatibility; custom Elasticsearch date-format unions
and analyzer choices may need a separate human evaluation.

A compatible Mapping does **not** establish that historical documents
have usable Event dates, correct `event_ids` links, evidence snippets,
Chinese word segmentation or accurate source extraction. Those need
separate read-only sample queries and SRAF retrieval/report checks.

This PR makes no ES Mapping modification, `_update_by_query`, reindex,
LLM extraction, data writeback, job restart or rerun. Its offline GitHub
test is wholly synthetic; it does not contact the operator's ES.
