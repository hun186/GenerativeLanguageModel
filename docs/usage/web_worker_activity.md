# Web Worker activity (WEB-04B)

Integration branch combines #385 local Web documents and #382 desktop Worker
activity; both dependencies must land before this can merge to main. The
existing validated Worker sidecar reader and activity clock are reused.
Only the current first page is scanned, capped at 24 calls. The browser sees
per-run pseudonymous endpoint and row aliases, numeric stream observations,
and last-observed clock text. No IP, model name, call ID, raw text, path or
clock anchor leaves the local service. No provider/GPU phase is inferred.
An unavailable/stale scope hides activity. Rows without observations are
counted separately. Terminal calls are excluded from active lifecycle view;
stream terminal events still awaiting a Worker return have no extrapolated
clock. This is not whole-run coverage and does not enable remote access.
