# Central Monitor: scheduled and concurrent GLM runs (proposed)

## Current limitation
The existing `prepare_ui()` creates one disposable monitor process per GLM
invocation in web mode, using one configured HTTP port. Multiple independent
scheduled invocations with the same port collide; subsequent jobs continue
without a GUI. The first job's termination shuts down its monitor. Worker
threads within one invocation are not separate Web servers. Dynamic port
selection is not the production solution.

## Target architecture
One supervised per-host Central Monitor owns the HTTP(S) listener, certificates,
operator authentication and dashboard for multiple independent runs. GLM
processes never bind an HTTP port in central mode. Separate daemon/service
configuration from producer registration settings. Preserve per-run local
Web mode for explicitly selected debugging and Windows desktop mode.

On Linux, use a service manager (e.g. systemd) for an independent lifetime;
startup before scheduled runs, restart independently, remain available when
idle. An owner-restricted Unix domain socket is the initial producer IPC
boundary, not an externally reachable HTTP ingest endpoint. Verify peer UID
and filesystem permissions; bounded versioned messages, no pickle or arbitrary
file locators from browsers. Initially support same-service-user producers;
cross-user membership and Windows IPC are separate acceptance scopes.

Each invocation generates a unique run ID and generation token, registers an
allowlisted label and bounded progress snapshot, then heartbeats. Keep
per-run reader state and source ownership separate. Duplicate/replayed
messages cannot merge two runs or regress the accepted sequence. Retain an
explicit completed/failed/unknown/lost-contact distinction, never infer success
from PID disappearance, heartbeat expiry or a completed slice. Never merge
different runs' quality/throughput denominators as a single result.

Registration/heartbeat/re-registration are best effort, bounded and off the
processing path. Service absence/restart must not block or abort inference;
retry with backoff and re-register full authoritative observable snapshot,
mark missing intervals explicitly. Never fall back to opening an HTTP port.
Central outage must not change job execution or sink semantics. Bound concurrent
runs, reader work, queue size, snapshot size, and retained history; show
capacity/staleness explicitly. Do not reuse stale run data on process/PID reuse.

## Operator experience
Run list (active, waiting, completed, failed, unknown), run-specific drilldown
using existing numeric document/worker/audit/quality views, and historical
summaries. Optional aggregate counters must identify scope and coverage.
No raw prompts, responses, paths, repair pairs, credentials or arbitrary file
access. Do not expose cancel until authorization and cooperative drain are
implemented and reviewed separately. This is a monitor, not a scheduler:
existing cron/systemd timers keep launching GLM.

## Security and configuration
Default proposed central HTTPS with persistent locally generated CA/server
certificate; no external CA required. Client must establish trust once via
verified CA/fingerprint; no disabled verification. Explicit private-interface
remote access requires operator authentication; retain optional manual certs
and mTLS. Cert lifecycle, auth, and listener belong to daemon only, not runs.
Remote off by default. Use service-specific ENV and a separate producer ENV
example; include safe defaults, startup commands, migration and troubleshooting.
Do not add nonfunctional ENV keys to copyable samples until parser and runtime
behavior exist. Existing supported example: 
`czjLLM/env_examples/web_monitor.env.example` (per-run; #395 candidate).
Future central-mode keys and service commands are not yet implemented.

## Prioritized implementation and acceptance
1. CENTRAL-01: versioned run registry, bounded leases/heartbeat and safe
   identity/generation tests.
2. CENTRAL-02: independent daemon and owner-restricted IPC; concurrent run
   registration, service restart, no port conflicts, client loss and rejoin.
3. CENTRAL-03: adapt runtime UI to central producer; retain standalone mode;
   two overlapping actual subprocesses plus a later scheduled invocation.
4. CENTRAL-04: multi-run dashboard and isolated existing projection readers,
   idle/active/terminal states; no invented history or raw paths.
5. CENTRAL-05: automatic persistent local PKI, operator auth, manual/mTLS
   compatibility, deployment examples and systemd service. Separate certificate
   provisioning from producers. Existing #395 is a staged TLS component.
6. CENTRAL-06: bounded history and retention, restart reconciliation, operator
   acceptance. Cross-host aggregation after per-host central mode works.

This is a design proposal and migration priority, not a deployed central
service. Fresh implementation CI/review and physical Linux acceptance needed.
