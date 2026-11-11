# Read-only per-run Queue receipt inventory

This operator-only command summarizes **one explicitly selected** Run Meter.
It is intended for the 19/13 stale receipt observation in Issue #302
without mutating any existing Queue, Success, Registry, SQL, ES, or LLM state.

## Windows / Linux usage

Run from the repository root with Python 3.10 or newer:

```bat
python scripts/inspect_queue_receipts.py --meter-file "D:\\private\\logs\\loadmeter_20261110.json" --human
```

```bash
python scripts/inspect_queue_receipts.py --meter-file "/private/logs/loadmeter_20261110.json" --human
```

Without `--human`, stdout contains one fixed-schema JSON object. The
operator must supply the **exact** per-run Meter path. There is deliberately
no default `./logs`, "latest" glob, or inferred cross-run link: these
previously caused missing or unrelated diagnostic snapshots. Use a stopped
Run for the most reliable snapshot; do not deploy or update the running
program merely to execute this tool.

The reader reuses the existing bounded 12 MiB strict Meter reader, rejects
symlink ancestors, invalid JSON and malformed row collections, and rejects
changes observed in file identity/size/mtime across collection. A successful
snapshot is **not atomic** and is not an authenticated record; an actively
writing process can still race or change bytes without a detectable metadata
change. The scanner reads no Queue item directories or file contents.

Only fixed fields and counts appear in stdout:
- global `queue.pending/running/completed` where valid;
- rows with exact integer `queue_pending=queue_running=0`, positive
  receipts, or unknown/malformed receipts;
- rows already marked `merged`, `writeback_failed_schema`,
  `writeback_failed`, `cancelled`, or `failed` with outstanding receipts;
- a cautious signal when global running is positive but **no** valid
  row running receipt is observed.

Status `REVIEW_REQUIRED` flags an observable mismatch, **not** proof that
the receipt is orphaned or that an LLM Worker has stopped. Status
`INCOMPLETE_EVIDENCE` means some counters are missing or malformed.
`OBSERVED_NOT_PROVEN` means a parsable snapshot without these detected
issues, **not** successful completion, correct scheduling, physical GPU use,
HTTP request success, or durable SQL/ES writeback. `UNAVAILABLE` means
the meter cannot be verified and does not imply an empty Queue. Exit 0 is
reserved for `OBSERVED_NOT_PROVEN`; other statuses exit 2.

Row identifiers, Run ID, endpoints, local paths, prompts, exception texts
and raw meter values never appear in the output. This tool neither
reconstructs a per-row timeline nor joins historical Runs: no cross-run
comparison is safe without a trusted Run identity and operator evidence.
It cannot fix the preexisting 19 or 13 receipts; changing them, replaying
work, and physical sink readback require separate, operator-controlled
authorization. See Issue #266 for real Windows/GPU/SQL/ES acceptance.

Offline regression: `tests/job_manager/test_queue_receipt_inventory.py`;
Hosted Linux and Windows 3.10/3.11 gates exercise real disposable JSON files
and redaction. Production systems are never accessed by CI.
