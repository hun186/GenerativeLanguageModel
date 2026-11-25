# Issue #313 — disposable SQLite durability/CAS proof only

This experimental adapter (`czjLLM/es_mode/quality_retry_sqlite_proof.py`)
is a **local, standalone, synthetic proof** of the immutable Quality retry
state machine, not a production durable adapter and **not wired** into
GLM's ES source scanner, LLM, Queue, YAML, Scheduler or Writer.

It requires an explicit operator-created **private directory**, explicit
`create=True` for a fresh DB, and a caller-provided 32+ byte secret.
It uses SQLite `BEGIN IMMEDIATE`, FULL sync, DELETE journal, fixed
HMAC-SHA256 identity keys and authenticated snapshots. The DB is
expected to live in a disposable local directory, never on SMB or in
shared storage. It contains no plaintext source document ID, pipeline
identity, prompt, article, output, remote endpoint or secret key.

Tests simulate two independent connections **and two separate spawned OS
processes** competing for the same quality repair revision in an explicitly
disposable local DB. The losing process must fail closed, and a restarted
reader must observe the single surviving `IN_FLIGHT` claim. The tests also
cover stale revision rejection, a process-local restart with unresolved
`IN_FLIGHT` state, failure count exhaustion, explicit reset and
tamper detection. This still does not prove inter-machine consistency, forced-kill mid-journal
recovery, hostile disk replacement, real ES sink ACK or Windows NTFS ACL. The caller-provided `verified_attempt_id`, verified
quality result and `operator_authorized=True` are **synthetic assertions**,
not authenticated evidence. Therefore **no integration or production
dispatch authorization is granted** by this PR.

A production design still requires authenticated source/pipeline
identity, verifiable sink readback, process/host crash reconciliation,
Windows NTFS ACL and real fsync acceptance, access-controlled operator
reset audit, migrations, rollback, support for multi-host producers and
independent security review. Do not apply this proof to `news_test`,
restart real jobs, requeue any document or claim Issue #313 closed.

## Connection-level integrity boundary

Each read and CAS now rechecks the schema version, required tables and HMAC key seal inside the same SQLite transaction before interpreting a missing state as a fresh budget. The existing file is opened with SQLite mode=rw, and read/error paths close their connections. This detects wrong-key replacements or modified seals/schema, not same-key rollback, hostile filesystem races or authenticated production storage. The disposable-only restrictions remain unchanged.
