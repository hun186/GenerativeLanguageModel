# MultiDim/SRAF search-field capability: template-only audit

Run from the GLM checkout:

```bat
python scripts/audit_multidim_search_fields_offline.py
```

This checks the **checked-in MultiDim task contract and Mapping YAML**
without Elasticsearch credentials or network requests. It reports a
small fixed list of consumer-relevant fields with codes:

- `KEYWORD_ONLY`: exact term field; do **not** assume partial Chinese
  token matches when a SRAF query searches these leaves.
- `TEXT_INDEXED`: text-indexed in the **template**; this alone does not
  establish a useful Chinese analyzer or partial-word recall.
- Explicit `index: false` on a primary `text`/`keyword` leaf
  causes a fixed `PRIMARY_INDEX_DISABLED` review result, rather than
  incorrectly reporting an available inverted index. A text subfield
  with its own `index: false` does not qualify as indexed search.
  Keyword doc-values queries may still be possible but can be slower;
  this probe does not prove all Elasticsearch query capabilities.
- `KEYWORD_PLUS_TEXT`: keyword leaf with at least one text subfield in
  the **template**. A consumer must explicitly query the appropriate
  subfield; existing ES documents may require reindexing to populate it.

Every report explicitly leaves analyzer availability, live
`news_test` Mapping, existing-document index coverage, and SRAF runtime
alignment as NOT_VERIFIED. In particular, Elasticsearch's native
`cjk` analyzer is a potential option for later **separate**
`_analyze`/Mapping checks, not automatically enabled by this PR.

This does not edit GLM's framework, change task YAMLs, create new
multi-fields, install ES plugins, run `_update_by_query`, reindex,
restart jobs, or make LLM calls. It complements #320's static contract
and #321's read-only live Mapping probe. An operator should check
live Mapping/analyzer behavior and SRAF queries separately before any
proposed ES index migration.
