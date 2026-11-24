# Integrated disposable candidate budget inspection — DRAFT (#313)

This integration branch includes exact pending #350–#353 dependency blobs. They must merge independently before this draft may be reduced to its own diff against accepted main, moved to ready, and reviewed/tested again. No auto-merge for this draft.

The explicit inspect_disposable_candidate_budget function composes actual adapter source-input comparison, current computed execution rehash, combined normalized profile/required-output observation and existing disposable SQLite read. Private RetryIdentity is HMACed by the existing ledger. Returns local candidate verdict, phase, failed repair count, revision and offline next-action projection. Repeated source/rule/semantic observations around the read fail closed on mismatch but are not atomic or authenticated. No raw payload, source ID or attempt ID returned. No ledger create, transition, reset, dispatch, provider call, ES write or automatic runtime invocation.

The integration test uses actual components, a synthetic read-only ES client and disposable temporary SQLite DB; test-only transitions seed exhausted history. Checks no new rows on inspection, output-only stability, edited input and changed rules, changed execution rejection and no buffer writes. Not live source or GPU acceptance. Actual dispatched/consumed provenance, sink ACK, restart reconciliation, production storage/multi-host consistency and operator authorization remain mandatory.

## Before a candidate exists

The draft also exposes inspect_disposable_pre_dispatch_budget without any JSON payload. It derives the same combined rule version as candidate validation through the shared rule snapshot, observes the same source and execution binding, and reads the same ledger state without normalizing a candidate or invoking a model. Integrated regression compares both projections for unassessed/exhausted state, output-only changes, edited source, rule change, and semantic drift. This read cannot replace an atomic claim or authorize runtime dispatch.
