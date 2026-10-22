# Reduction v1.1 — legacy filesystem inventory (read-only)

The L3 Reduction GC owns only artifacts with verified `.retention.json` markers.
Pre-L3 checkpoint runs and unmarked runtime directories remain permanently
unowned by that collector. This standalone inventory supports a future
**explicitly reviewed** maintenance/migration decision without changing that boundary.

## Operator commands

One explicitly approved item workspace:

```bash
python -m czjLLM.cli_tools.reduction_legacy_audit --item-root /path/to/item
```

Or an approved Prompt container (immediate child item directories only):

```bash
python -m czjLLM.cli_tools.reduction_legacy_audit --prompt-root /path/to/Prompt --max-scan-entries 5000
```

Repeat `--item-root` / `--prompt-root` for additional existing roots.
Overlapping item/Prompt scopes, repeated paths, and item-root versus
item/.reduction aliases are normalized **before discovery** so repeated
roots do not inflate statistics or exhaust the scan budget. Missing roots fail instead of returning an
apparently complete empty report. The default scan
bound is 10,000 entries shared across all roots. The CLI exits with code 2
when truncated, invalid, or unable to inspect an entry: do not treat the
partial counts as a complete inventory.

## Counter meanings

- `marker_files_present_unverified`: marker exists as a regular file but its
  ownership, schema, integrity, age, and lease have NOT been checked.
- `marker_nonregular`: marker is a symlink, directory or special filesystem entry.
- `unmarked_checkpoint_manifest_present_unverified`: 64-hex checkpoint run
  directory with a regular `run.json`. This does NOT prove run/round-chain
  validity, inactivity, resume safety, or migration eligibility.
- `unmarked_checkpoint_manifest_missing` /
  `unmarked_checkpoint_manifest_nonregular`: manifest absent or not a regular file.
- `unmarked_runtime_rounds`: recognizable `round-0002`-style unmarked directory.
- `unrecognized_unmarked_directories` / `skipped_containment`: unexpected
  directory name or containment failure, never implicitly deletion eligible.
- `scanned_entries`: traversal budget usage, including Prompt child names.
- `candidate_directories`: discovered direct child directories of approved
  Reduction checkpoint/runtime parents. `scan_limit_reached=true` means
  reporting coverage is incomplete.

The JSON output contains only counts and flags, never directory names, paths,
document IDs, checkpoint keys, prompts, outputs or credentials.

## Exclusions and safety contract

The audit is strictly **read-only**: no ownership adoption, migration,
marker creation, lease, checkpoint resume, deletion, tombstone, or GC mutation.
It never parses run/round JSON or inspects source contents. Symlink and Windows Junction/reparse roots (including intermediate path
components) are rejected; junction/symlink candidate directories are ignored,
and symlink markers/
manifests never opened. Approval scope follows the L3 direct-child
traversal; nothing is recursively discovered under unrelated item folders.

Not inventoried: `_stage_outputs`, `_stage_merges`, Success/TODO outside
managed Reduction runtime, sources, backups, logs, final output, SQL/ES
persisted results or semantic caches. These remain outside L3 GC ownership.

Any future **actual migration** needs a separate reviewed ownership and
rollback contract, reliable checkpoint/round-chain validation, active lease
coordination and operator opt-in. This inventory does not provide that
contract, and Reduction semantic fingerprints are unchanged.
