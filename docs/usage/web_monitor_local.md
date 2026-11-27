# Local Web monitoring bootstrap

Default behavior is unchanged. For an explicit read-only monitor for the
shared SQL-mode runtime UI entry point, use:

```dotenv
GLM_UI_MODE=web
GLM_WEB_HOST=127.0.0.1
GLM_WEB_PORT=9010
```

Run GLM normally, then open http://127.0.0.1:9010/ from the same host.
For a remote operator use SSH local forwarding, e.g. forward local port
9010 to the server's 127.0.0.1:9010. Do not publicly proxy this initial
unauthenticated local service; non-loopback configuration is rejected.

The disposable monitor subprocess serves numeric observed event totals,
elapsed time and delivery completeness. Queue overflow marks the view
incomplete, never blocks intentionally waiting for space. Only the fixed
static UI and GET status API are exposed; no raw logs/paths/prompts,
cancellation, file reads, audit or quality data. Browser closure does not
own the process. Port conflict or startup failure falls back to console.

This is not Windows GUI parity: ETA, document/worker views, audit,
quality, logs, authentication/TLS, remote control and both mode are
subsequent work. Other runtime entry paths and real Linux/Windows
execution require acceptance. All processes stop with the current run.
