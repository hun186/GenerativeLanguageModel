# Reduction retention and safe GC (L3)

Reduction filesystem retention is opt-in operational maintenance. It does not
participate in execution, processing, aggregate, manifest, or checkpoint
fingerprints. Existing deployments perform no deletion unless enabled:

```yaml
reduction_retention:
  enabled: false
  dry_run: false
  checkpoint_terminal_ttl_days: 14
  checkpoint_incomplete_ttl_days: 30
  transient_runtime_ttl_hours: 24
  cleanup_transient_on_success: true
  max_delete_entries_per_sweep: 100
  max_delete_bytes_per_sweep: 1073741824
  max_scan_entries_per_sweep: 10000
```

Unknown keys, non-boolean boolean fields, non-finite/negative TTLs, and
non-positive/non-integer limits are rejected. Incomplete checkpoint TTL must be
at least the terminal checkpoint TTL. Zero TTL means immediately eligible only
after the artifact is inactive.

## Ownership and safety

New checkpoint runs and runtime rounds receive a bounded `.retention.json`
marker. Unmarked pre-L3 directories are never adopted or deleted. Checkpoint
deletion additionally validates `run.json`, contract/run identity, and the full
committed round chain. Corrupt or unknown artifacts are retained.

Execution uses an expiring, refreshed filesystem lease. GC takes an exclusive
claim, repeats ownership/identity/TTL/containment/lease/budget checks, then
atomically renames the directory to a verifiable same-parent tombstone before
recursive deletion. Directory symlinks are never followed. Stale lease expiry
only removes the active exclusion; it never bypasses TTL.

Dry-run performs validation and bounded budget planning without marker, lease,
claim, rename, or delete mutation. Maintenance failure cannot change an already
successful final output or persisted writeback into a failed inference.

## Explicit exclusions

L3 never discovers SQL/ES persisted outputs, processing identities,
`AggregateOutput`, Collection Manifest files, source/backup/final outputs,
pending/recheck/reduction JSONL logs, LLM audit files, `_stage_outputs`,
`_stage_merges`, or TODO/RUNNING/Success outside managed `.reduction/runtime`.
No second cross-run member-result cache is introduced; L1 SQL/ES persisted reuse
remains authoritative.
