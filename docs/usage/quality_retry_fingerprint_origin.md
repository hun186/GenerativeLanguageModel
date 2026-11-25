# Quality retry identity — computed origin (Issue #313)

The real persisted freshness binder accepts auto and explicit literals. A literal,
including a 64-character hex string, may still control the legacy freshness policy
but is not proof of an actual computed execution identity.

After a successful auto bind, observed_computed_execution_fingerprint(ctx)
returns the digest only if it matches the expected context value. A disabled,
literal or failed bind clears the observation. Rebinding an already resolved
adapter config treats its value as literal. This is intentionally conservative.

The observation is process-local; it is neither authenticated evidence nor a
fresh hash of mutable executable state. Custom executable metadata is caller
controlled. Actual source namespace/document identity, immutable effective
execution and quality rule, durable claim, verified repair completion and
sink reconciliation still require separate integration. No new retry, ES,
YAML, or Queue behavior is enabled. The legacy binder return and adapter
freshness value are unchanged. Mandatory Linux/Hosted Windows contract tests
cover actual binder auto/literal/failed/disabled and mismatch behavior.

## Current semantic re-observation

The ES-only explicit reobserve_computed_es_execution_fingerprint checks the actual context/adapter binding, enabled rerun fingerprint, original computed marker and a fresh hash of the built-in effective executable using the existing semantic runtime. Literal, drifted, mock or caller-supplied explicit executables are unavailable. No rebinding, configuration mutation, observer setup, LLM or retry accounting. Equal hashes describe the read-time semantics only; they do not establish immutable execution, consumed input or authenticated completion.
