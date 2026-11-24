# Quality retry source observation — #313

The explicit ElasticsearchAdapter.observe_quality_retry_source(logical_id)
method uses the already connected client for read-only info, settings and
exact search. It is not called by normal discovery or Consumer. The narrow
initial scope is a single concrete source/target index, string _id or
string business key, exactly one hit with a complete search response.
The business key is checked against returned _source; aliases, duplicate
keys, arrays, incomplete responses and changed namespace fail closed.

The private scoped ID includes cluster UUID, index UUID, concrete index
and real document _id. This prevents accidental namespace collisions;
the future ledger must HMAC it. No source content or identifiers are
logged or persisted by this method. The check is not atomic with later
writeback, not TLS authentication, and not proof of source immutability,
routing, output identity or authorized repair. Existing scan and sink
behavior remains unchanged. No automatic calls or retry-budget activation.
Separate live read-only permission, effective configuration and source/sink
reconciliation acceptance remain mandatory before integration.
