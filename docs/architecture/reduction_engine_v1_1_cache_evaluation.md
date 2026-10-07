# Reduction Engine v1.1 transient semantic/member cache evaluation

## Decision

Do **not** implement a second transient semantic/member result cache yet.

Reduction Engine already has distinct authorities for the retry scopes that are
proven in production:

- persisted SQL/Elasticsearch destination output plus optional processing
  identity is the cross-run reuse/freshness authority;
- committed hierarchical checkpoints are resume authority;
- transient runtime round workspaces are reconstructable execution artifacts,
  not result caches.

Adding a persistent or global member-result cache would create a competing
authority and a new source-derived data retention/privacy surface. Adding an
in-memory cache without a measured duplicate-call workload would add
concurrency, cancellation, accounting, and failure semantics without
demonstrated production benefit.

## Evidence reviewed

The evaluation reviewed the active contracts and implementation around:

- `czjLLM/reduction/execution.py`: executable semantic fingerprints, execution
  contexts, cancellation, observer and result contracts;
- `czjLLM/reduction/stage.py`: member scheduling, ordering, partial success,
  cancellation, metrics and hierarchical continuation;
- `czjLLM/reduction/persisted_freshness.py`: persisted SQL/ES processing identity and
  cross-run freshness binding;
- `czjLLM/reduction/runtime_semantic.py` and `czjLLM/reduction/reducers/semantic.py`: semantic LLM
  call boundary and reducer contract;
- semantic runtime/reducer tests and persisted processing-identity tests;
- the v1 operator guide's retry/reuse authority table.

No source or test currently establishes a material workload where the same
effective executable semantics repeatedly process the same member payload in a
single run often enough to justify a cache.

## Why a disk/global cache is rejected

A disk/global cache would have to answer all of the following before it could be
safe:

1. Is it authoritative over a fresh persisted SQL/ES destination result?
2. How is it invalidated when prompt/task/model/tokenization semantics change?
3. Does it duplicate or conflict with committed checkpoint resume?
4. Which source/prompt/output payloads are retained, for how long, and under
   which deletion/ownership rules?
5. How are credentials, private endpoints and unrelated provenance excluded?
6. How does it preserve partial-success, cancellation, retry and audit semantics?

The current architecture already answers these questions at the persisted
destination and checkpoint boundaries. Re-answering them for another durable
store is not justified by present evidence.

## Re-open criteria

Reconsider a cache only when production telemetry or a reproducible workload
shows a material amount of duplicate **same-input + same-effective-semantics**
execution and enough LLM cost/latency to justify added complexity.

If reopened, the first acceptable design should be deliberately narrow:

- explicit opt-in;
- bounded by entry count and/or memory estimate;
- run-scoped and non-persistent by default;
- keyed by hashed input identity plus the existing executable semantic
  fingerprint, without persisting plaintext prompts or payloads in the key;
- successful immutable `ExecutableResult` values only; failures and
  cancellation are never cached;
- cache state/policy remains operational and excluded from semantic
  fingerprints;
- no change to persisted SQL/ES reuse authority or checkpoint authority;
- no hard-kill or cancellation masking while waiting for work;
- observer/accounting semantics must distinguish attempted logical members from
  actual external executions before production rollout.

A parallel in-flight coalescer is a separate decision and must not be smuggled
in as a cache implementation: sharing one transient failure across duplicate
members can change retry and partial-success behavior.

## Outcome

The backlog evaluation item is complete, but implementation is **deferred**.
This is an intentional architecture decision, not an unimplemented stub. The
next v1.1 candidate may proceed independently.
