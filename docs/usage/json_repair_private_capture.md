# Opt-in local-only private JSON repair before/after snapshots — Issue #309

**Security-sensitive / draft feature.** This is NOT enabled by default.
Do not deploy or turn it on for private workstations merely because Hosted CI passes.
Operator review of the local Windows NTFS permissions and storage location is required.

## Why it is separate from the Quality events

The ordinary per-run `processing_quality_events_*.jsonl` contains strict,
payload-free event IDs, times, run ID, basename-only slice hint and
numeric repair metrics. It must never contain raw JSON. Prior historical
repairs cannot be reconstructed from those metrics.

During a successful, already-parseable LLM JSON repair, the Worker has
exact `before` and `after` strings available **in memory**. Only when
explicitly opted in, it writes the two strings into a private file named
by a newly-generated UUID4 `event_id`, exactly matching the success
quality event. The GUI must look up both the **exact run ID and event ID**,
never the 16-character basename-derived slice hint (which may repeat
for unrelated documents). No failed or partial JSON repair is captured.

## Explicit opt-in, requiring local private filesystem setup

Before starting a new Run, an authorized operator must create a
**pre-existing, absolute, local-only private capture directory** on a
protected local volume, with permissions that allow only the operator
account. On Linux the directory must have mode `0700`; the implementation
reads `/proc/self/mountinfo` and allows only recognized local filesystem
types (ext2/3/4, xfs, btrfs, zfs, f2fs, tmpfs). A Linux NFS/CIFS,
FUSE/SSHFS, overlay/container filesystem, unknown type or missing mount
information is rejected **before saving**. This filesystem check does
not prove the underlying physical block device is local and must not
replace operator review of mounts or backup policies. On Windows
`GetDriveTypeW` must classify the drive as `DRIVE_FIXED` (reject mapped
SMB/remote or unclassifiable drives); NTFS ACLs still require manual
verification (Python mode bits alone do not protect them). Do not use
SMB/network shares, OneDrive/synced/cloud folders, user-shared storage,
public repos or container image layers.

Set both runtime configuration variables:

```bat
set CZJLLM_JSON_REPAIR_CAPTURE=1
set CZJLLM_JSON_REPAIR_PRIVATE_DIR=<absolute-private-local-directory>
```

Unset/disable `CZJLLM_JSON_REPAIR_CAPTURE` to stop **future**
captures. Disabling recording does not destroy already saved sensitive
plaintext; the on-demand GUI reader can still retrieve prior selected
Run/event pairs when the directory remains configured. Use the
explicit confirm-and-clear button to remove the selected Run's files,
or follow an approved local retention procedure. No automatic TTL,
cross-run deletion or hidden purge is implemented.

If enabled while the directory is absent, relative, a symlink/reparse
point, or unsafe according to the local validator, capture fails with a
fixed `PRIVATE_JSON_REPAIR_CAPTURE_UNAVAILABLE` warning and **does not
change the LLM repair result**.

## Bounded private storage

- New files are **plaintext JSON** containing both strings, a UUID4
  event ID and hashed run identity, written exclusively (no overwrite).
  On POSIX the created Run directory is 0700 and files are 0600;
  on Windows protect/check inherited ACLs manually.
- Up to 80,000 Unicode characters on each side and 512 KiB per snapshot.
  Maximum 48 snapshots and 16 MiB per Run namespace. Excess cases are
  intentionally not saved and the ordinary numeric audit is unaffected.
- Files are local-only and no-follow; unknown artifacts or hardlinked
  snapshots fail closed. A cooperating interprocess lock bounds capture
  counts. Noncooperating malicious local processes, abrupt disk failure,
  unauthorized account access and external backup/sync are NOT covered.
- The operator selects a row in **🔎 JSON 差異** and explicitly chooses
  **檢視所選案例原始／修復全文**. The viewer reads only the exact
  Run/event-matched file after basic type, size, integrity and ID checks;
  two text panes highlight common prefix/suffix and changed middle.
  This is a **character-level visual aid**, not semantic consistency
  or proof that all original news events were retained.
- **清除所選 Run 的私有原文** requires a confirmation dialog and deletes
  only exact capture files under the selected hashed Run directory.
  It does not alter Queue/Worker/LLM/SQL/ES/quality events. Empty lock
  metadata may remain. Standard unlink is NOT secure erasure for SSDs,
  disk snapshots or backups; use appropriate encrypted-volume and
  system-level retention policies.
- No raw input, output, private directory path or exception message is
  appended to normal logs or shown in a failed-capture warning.

## Review and acceptance

Hosted synthetic Linux/Windows tests prove opt-out defaults, exact Run/event
matching, bounded writes, fail-closed corrupted records, symlink/hardlink
cases, explicit deletion and ordinary quality-event redaction. These
**do not validate physical Windows NTFS ACLs or user workstation behavior**.

Because this feature stores the original source/model output, require
formal security review and explicit operator authorization before
enabling it in production. It is independent of the low-risk #308
popup/layout PR and does not change actual JSON repair, retry, Queue
claim/ACK, or ES/SQL sink success rules.

### Nested per-run mount guard (2026-11-11)

Verifying only the configured private root is insufficient: an existing `run-<digest>` child may be a separately mounted NFS/CIFS filesystem. On Linux the implementation now fails closed unless the **actual per-run directory** passes the same `/proc/self/mountinfo` local-filesystem allowlist, before creating the lock or snapshot; read and manual clear are guarded too. Synthetic regressions cover existing and freshly created child folders. Mount changes after validation, remote block devices, local adversaries, ACLs, backups and host-level access are not proven secure; operator review remains mandatory.

An additional fail-closed rule rejects any remote/unknown **matching ancestor mount** (not merely the longest mountpoint). This addresses an older local child mount hidden by an NFS/CIFS overmount on its parent; it may conservatively refuse some valid complex local mount layouts. Never bypass the guard for convenience.
