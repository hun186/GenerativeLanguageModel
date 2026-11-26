# Cross-platform GLM monitoring roadmap

WEB-01 introduces a platform-neutral event vocabulary and a numeric run
projection. The existing Tk client keeps the same event strings and behavior.
The projection is not yet connected to an HTTP service or a production run.

Planned sequence:
1. Bounded read-only local HTTP service, explicit opt-in and port configuration;
   loopback only until authenticated remote TLS access is implemented.
2. Runtime lifecycle integration and bounded nonblocking event delivery;
   failures must never stop GLM work. Default Windows/Tk and Linux/console
   behavior remains unchanged.
3. Shared document/worker and audit/quality projections, with stale-evidence
   semantics, capped memory and one background reader per run.
4. Authenticated remote access, safe cancel via existing cooperative drain,
   separately authorized raw diagnostics, and platform acceptance.

Never expose arbitrary files, credentials, prompt text, raw log messages,
repair samples, or exception payloads by default. No network control or
external dependencies are added in WEB-01. Completion counters are not
independent SQL/ES sink readback. Browser lifetime must not own run lifetime.
