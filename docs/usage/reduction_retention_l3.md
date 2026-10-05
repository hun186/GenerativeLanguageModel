# Reduction retention and safe GC (L3)

This is the detailed retention contract. For lifecycle context and the rest of
the operator surface, see the consolidated
[Reduction Engine v1 guide](reduction_engine_v1.md).

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

The canonical CLI entry parses this root mapping once and attaches the frozen
policy as `ctx.reduction_retention` before TXT/Table/SQL/ES work is scheduled.
Invalid policy fails early; runtime maintenance consumes the normalized object.
Retention remains outside every semantic fingerprint.

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

Production grants `ctx.prompt_dir` explicitly as a prompt-container root.
Discovery inspects only its immediate non-symlink item directories and their
recognized `.reduction/{checkpoints,runtime}` children; it never recursively
walks arbitrary descendants. Thus an expired historical item remains eligible
when absent from the current scheduler/registry set. Container children and
managed artifact entries both consume the configured scan bound.

Interrupted-GC tombstones are recovered only when their exact filename token,
original-name suffix, tombstone marker, retained ownership marker, artifact kind,
and direct-parent containment agree. Recovery consumes the same entry and byte
budgets and reporting as ordinary deletion; dry-run never removes tombstones.

## Explicit exclusions

L3 never discovers SQL/ES persisted outputs, processing identities,
`AggregateOutput`, Collection Manifest files, source/backup/final outputs,
pending/recheck/reduction JSONL logs, LLM audit files, `_stage_outputs`,
`_stage_merges`, or TODO/RUNNING/Success outside managed `.reduction/runtime`.
No second cross-run member-result cache is introduced; L1 SQL/ES persisted reuse
remains authoritative.

Pre-L3 checkpoints with valid `run.json` but no `.retention.json` remain
permanently unowned. Resume never auto-adopts them; a future migration would
require a separate explicit ownership contract.
