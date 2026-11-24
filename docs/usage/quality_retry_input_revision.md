# Source input revision observation (#313)

The explicit adapter method observe_quality_retry_inputs compares caller-supplied exact primary and configured stage string inputs to the same unique concrete ES search hit used for source identity. Only single-output, disjoint input/target paths are supported. Output/meta/time-only updates do not change the private input digest; actual input edits require a new matching observation. Missing, non-string, ambiguous or unsupported configuration fails closed. Normal discovery and writes are unchanged.

The private revision identity contains scoped document identity and a bounded content digest; never log or persist this raw identity, and HMAC it before any future ledger use. It is not an atomic ES snapshot, authenticated provenance, or authorization to reset a budget. Actual dispatched/consumed input proof, route and output identity, rule binding and sink reconciliation still need acceptance. The existing mandatory source-observation Hosted suites cover this narrow observation.

When both output_col and output_cols are supplied, the narrow observation requires one matching output; explicit output_cols takes precedence for resolution, and conflicting/multiple/malformed declarations fail before any ES read. This prevents generated secondary fields from becoming input revision evidence.
