# Project-local JSON repair before/after snapshots (auto cache and manual override)

**Sensitive plaintext feature.** New captures are enabled by default ONLY
when GLM can create/verify a protected local project cache. Set
`CZJLLM_JSON_REPAIR_CAPTURE=0` (or `off`) to stop new captures;
**unset does NOT disable capture**. If local NTFS/POSIX permissions are
unverified, recording fails closed without changing JSON repair.
Hosted CI is not operator host/backup policy verification.

## Why it is separate from the Quality events

The ordinary per-run `processing_quality_events_*.jsonl` contains strict,
payload-free event IDs, times, run ID, basename-only slice hint and
numeric repair metrics. It must never contain raw JSON. Prior historical
repairs cannot be reconstructed from those metrics.

During a successful, already-parseable LLM JSON repair, the Worker has
exact `before` and `after` strings available **in memory**. Only after the
automatic cache checks pass (or the operator configures a private override),
it writes the two strings into a protected file named
by a newly-generated UUID4 `event_id`, exactly matching the success
quality event. The GUI must look up both the **exact run ID and event ID**,
never the 16-character basename-derived slice hint (which may repeat
for unrelated documents). No failed or partial JSON repair is captured.

## Optional manual directory override

For ordinary Windows/Linux operation **no directory input is required**.
If a custom directory is needed, an authorized operator must create an
**absolute, local-only private capture directory** on a protected volume,
with permissions that allow only the operator account. On Linux the directory must have mode `0700`; the implementation
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

For an **optional manual override only**, set both runtime variables:

```bat
set CZJLLM_JSON_REPAIR_CAPTURE=1
set CZJLLM_JSON_REPAIR_PRIVATE_DIR=<absolute-private-local-directory>
```

Set `CZJLLM_JSON_REPAIR_CAPTURE=0` or `off` **explicitly** to stop
future captures. **Do not unset this variable to disable capture**:
unset means automatic capture is enabled if safe. Disabling recording
does not destroy already saved sensitive plaintext; the on-demand GUI reader can still retrieve prior selected
Run/event pairs when the directory remains configured. Use the
explicit confirm-and-clear button to remove the selected Run's files,
or follow an approved local retention procedure. No automatic TTL,
cross-run deletion or hidden purge is implemented.

If a manually overridden directory is absent, relative, a symlink/reparse
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

Hosted synthetic Linux/Windows tests prove auto-safe defaults, explicit opt-out, exact Run/event
matching, bounded writes, fail-closed corrupted records, symlink/hardlink
cases, explicit deletion and ordinary quality-event redaction. These
**do not validate physical Windows NTFS ACLs or user workstation behavior**.

Because this feature stores the original source/model output, treat
physical host NTFS ACLs, filesystem placement, backup/sync and retention
as separate operator acceptance boundaries. Automatic capture fails closed
if local checks cannot be verified. It is independent of the low-risk #308
popup/layout PR and does not change actual JSON repair, retry, Queue
claim/ACK, or ES/SQL sink success rules.

### Nested per-run mount guard (2026-11-11)

Verifying only the configured private root is insufficient: an existing `run-<digest>` child may be a separately mounted NFS/CIFS filesystem. On Linux the implementation now fails closed unless the **actual per-run directory** passes the same `/proc/self/mountinfo` local-filesystem allowlist, before creating the lock or snapshot; read and manual clear are guarded too. Synthetic regressions cover existing and freshly created child folders. Mount changes after validation, remote block devices, local adversaries, ACLs, backups and host-level access are not proven secure; operator review remains mandatory.

An additional fail-closed rule rejects any remote/unknown **matching ancestor mount** (not merely the longest mountpoint). This addresses an older local child mount hidden by an NFS/CIFS overmount on its parent; it may conservatively refuse some valid complex local mount layouts. Never bypass the guard for convenience.


## 2026-11-17: Automatic project-local cache (new default)

The optional manual directory override above remains available. In the
new release, successfully repaired JSON is saved by default only after a
strict local security check. On Windows and Linux the cache is located at:

    <GenerativeLanguageModel>/.runtime-private/json_repair/

The program finds this from its installed source path, NOT the process cwd.

- Windows fixed local NTFS/ReFS: secure protected owner/SYSTEM/Administrators
  ACL created atomically via Win32; unsafe existing ACLs and reparse paths
  are rejected. POSIX: local allowlisted filesystem and mode 0700.
- The source before and after repair is stored only in this dedicated
  operator-account private cache, never in routine Quality JSONL or LLM CSV.
- Each snapshot is readable for up to 72 hours. Expired files are pruned
  opportunistically at GLM batch startup, during a new successful repair or on opening the repair
  GUI. There is no background janitor on an otherwise idle host.
- The pre-existing per-case and per-run limits still apply. There is also
  a 128 MiB active cross-run quota and bounded directory traversal.
- The original GLM GUI has the existing JSON differences command. It opens
  only an exact, nonexpired Run/event-matched snapshot. Uncaptured historical
  repairs cannot be recovered from the statistics-only audit.
- Set CZJLLM_JSON_REPAIR_CAPTURE=0 to disable NEW automatic captures.
  CZJLLM_JSON_REPAIR_PRIVATE_DIR remains available as a manual path override
  subject to the existing filesystem restrictions and operator ACL review.
- Cache files are plaintext and ordinary removal is NOT secure disk erasure.
  A Git ignore rule prevents commits, but backup/sync/7z/Docker packaging
  must also exclude .runtime-private explicitly. Do not use shared SMB/NFS
  mounts or synced checkout folders for sensitive JSON.
- Windows GUI and Linux scheduled jobs on different machines have independent
  local caches. The Windows GUI cannot magically retrieve a Linux-only cache;
  do not automatically synchronize plaintext repair records.
- If the security check or quota fails, normal JSON repair and ES/SQL
  processing continue; the console displays only a fixed failure code.

This new default is best-effort operator-local storage, not encrypted at rest,
a defense against malicious local users, or proof of physical host acceptance.
Hosted CI and operator native NTFS/ACL verification remain distinct.
