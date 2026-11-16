# GLM CI early MultiDim feedback (no weakened release gate)

The GitHub CI `offline-e2e` job now executes these existing **synthetic,
non-network** checks immediately after dependency setup and E2E test
collection: Quality retry budget, Event/Timeline and Rerun, GLM→SRAF
search-consumer schema v1, Mapping read-only probe, and nested-only
sampling/privacy tests. Previously they ran only *after* the longest
production E2E suite and several unrelated regressions.

A new small structural regression (`tests/test_ci_multidim_fast_gate.py`)
ensures each check remains included exactly once, keeps its required
test files and strict fail behavior, runs after setup, and completes before
`Run offline production E2E gate`. The existing full production E2E and
all later CI steps are **not** removed, skipped, made advisory or replaced;
the only change is fail-fast *ordering within the same Hosted Linux job*.

This does **not** make total CI faster when all tests pass; it helps
fail a wrong Mapping/Profile schema early, before long E2E work. Windows
Hosted gates remain separate. Queued self-hosted Windows runs must not be
counted as passed. No real ES/LLM/private connection/production run is
involved or permitted by this CI-only PR.
