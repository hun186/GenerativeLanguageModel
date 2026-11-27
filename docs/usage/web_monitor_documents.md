# Local web document progress (WEB-04, initial slice)

The same strict meter reader and document projection used by the Windows UI
provide a redacted first page to the local read-only Web monitor.
One background reader refreshes every two seconds regardless of HTTP client
count. A missing, corrupt, stale or replaced meter never appears as a
successful empty run. Queue delivery loss suppresses document data.
The browser cannot choose a path or read arbitrary files.

Only fixed stage labels, counts and per-run pseudonymous document aliases
are exposed. Original row keys, filenames, model/IP, prompts and audit
details remain private. First page is limited to 12 rows with an explicit
omitted count. Authentication, full pagination and search, Worker stream
activity and Audit detail follow separately; no public/remote listener yet.
