# MultiDim ES no-event output and task-owned rerun policy

## Scope

This contract is only for ES YAML tasks using
`validator: multidim_event_time`. It does **not** modify the general GLM
parallel execution framework, other tasks, `validator: date`, any private
connection `.py`, Elasticsearch mappings, or production documents.

A legitimate no-event article may have `Event: []` and
`evidence_snippets: []`. This is distinct from a missing output, a broken
JSON object, or a linked citation without an Event.

## Policy and guarantee

The per-task opt-in option:

```yaml
rerun:
  required_output_checks:
    - path: multidim_event_json
      validator: multidim_event_time
      allow_empty_events: true
      min_valid_count: 1
      relative_to_output: false
```

`allow_empty_events` defaults to **false** when absent (or when not the
boolean `true`). An opt-in accepts only nonempty arrays of article blocks
where **every block** explicitly has `Event: []`, the **full current
MultiDim Output Profile** accepts every block (including article-date
field consistency), and `Person`, `Involved_Parties`, `Impact`,
`Event_Timeline`, and `evidence_snippets` are all empty. In particular,
an orphan timeline/evidence row, incomplete article date fields, or
unrecognized schema key cannot use this path. Mixed no-event and real-event
blocks remain review-required rather than silently passing.

Normal Event-first validation and explicitly unknown or partial times
remain unchanged. **No evidence coverage minimum is introduced.** A
valid Event with zero evidence snippets is still a structurally valid
output, but SRAF should not claim it has attributable evidence.

### Important limit: source truth is NOT proven

Even full Output Profile success cannot establish whether a model
incorrectly missed an event in the original article. The no-event path
is a *structural completion classification*, not a source-fidelity
attestation. It should be paired with read-only sampling of original
articles and a separately reviewed, bounded Quality repair policy.
Do **not** use the opt-in to hide known source-extraction defects.

### Deployment / authorization

The sample ES task YAMLs opt in, but editing/merging YAML **does not
authorize** an operator to deploy, activate ES work, or initiate Reruns.
Prior to any actual job launch, verify the effective per-task private
connection and task YAML configuration, pending counts, live TLS/server
identity, and the ES index snapshot through read-only inspection.
Existing `pipeline_hash`, `force_since`, model tag/fingerprint,
`stale_after_days`, missing-output checks, and explicit operator
overrides can still independently make a document pending. No ES
rewrite, index mapping change, LLM call, or auto-replay is performed
by this source PR.

## Tests

`tests/es_mode/test_multidim_event_time_rerun_contract.py` covers the
opt-in/default boundary, an Output Profile-accepted empty Event,
invalid article dates, dangling linked arrays, mixed blocks, and both
ES pending adapters with independent pipeline-hash forcing.
