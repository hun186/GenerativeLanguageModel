# GLM MultiDim search-consumer contract v1 (offline)

This is a **task-scoped interoperability contract** for the
`InfoExtraction-MultiDim-SQLFriendly-to json format` task.
It does not change or constrain the general GLM parallel execution framework.

## Files

- `czjLLM/es_mode/contracts/multidim_search_v1.json`: pinned, portable
  consumer-visible field paths, ES nested types, date field formats, event
  linkage rules, and explicit empty-output semantics.
- `czjLLM/config_es/schemas/InfoExtraction-MultiDim-mapping.yaml`: the
  producer's current Mapping **template**, not proof of live-index Mapping.
- `tests/es_mode/test_multidim_search_contract_v1.py`: offline tests
  binding the manifest to the Mapping template and the real Output Profile.

A consumer such as SRAF may copy/pin this version and run its own offline
query and Evidence tests against it. **Do not import GLM at SRAF runtime**
or create a third repository just for this initial contract.

## Semantics and limitations

- `multidim_event_json` is a nested array of article blocks. Each block
  has local `Event[].event_id`; `event_ids` in Timeline, Impact, Person,
  Involved_Parties and evidence_snippets refer only to that local block.
- `Event_Timeline: []` and `evidence_snippets: []` can be valid. A
  no-event output can be structurally valid and requires the task-owned
  `allow_empty_events: true` option to be accepted by the rerun guard.
  Empty Evidence does not certify that the original article was irrelevant.
- `article_date_iso` is not the Event date; no Report or Evidence consumer
  should invent exact event days from publication date or year/month
  precision.
- A Mapping `keyword` leaf is **not** a Chinese full-text field. The
  contract faithfully records the current field types; it does not add
  `cjk` fields, install plugins, update Index Mapping or reindex data.
- A producer's valid JSON and a successful ES index operation do **not**
  imply SRAF has a date-linked, source-grounded citation. SRAF must run
  its separate topic, timestamp, block-scope and evidence validation.

## Versioning

Treat `multidim_search_v1.json` as immutable for **incompatible**
consumer changes: rename or change the major version before changing
nested paths, key names, date formats, or value semantics. Additions of
optional fields can be included without breaking v1, but still need
independent CI review. A SRAF-side pinned copy is updated by a separate PR,
never silently pulled from the network at runtime.

## What CI proves

The repository CI only compares GLM's checked-in Mapping template, Output
Profile and task-specific synthetic examples. It does **not** inspect the
private live `news_test` Mapping, evaluate actual Elasticsearch analyzers,
contact SRAF, read confidential documents, run LLMs, or authorize an
`_update_by_query`/reindex/rerun. Real-index and source-fidelity acceptance
remain separate operator-controlled work.
