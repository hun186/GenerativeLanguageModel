# Read-only queue recovery inventory (phase 2d)

This operator tool complements the accepted PR #254 no-overwrite queue moves.
It **does not** repair, replay, move, unlink, hash, open or modify any TODO,
RUNNING, Success or staging file; it never connects to LLM, SQL or ES.

A crash may interrupt the exclusive hardlink-create + source-unlink sequence,
leaving the same inode with two names (for example TODO and RUNNING). A crash
may also leave a Success output beside its RUNNING source or a disposable
`.success-publish-staging` file after Success publication. None of these
are sufficient evidence to automatically remove files or dispatch a retry.

## Operator usage

Stop every producer, Worker, consumer and stage merger writing to the relevant
item first. From the repository root, pass the **item directory itself**, not
a TODO subdirectory. **The accepted scanner remains POSIX/Linux only.**
Windows Python 3.10/3.11 standard-library directory traversal cannot guarantee
handle-relative no-follow behavior. The **default Windows CLI** therefore
continues to return `UNSUPPORTED_SAFE_SCAN_PLATFORM` and exit 2.

Phase 2f introduces separately gated `--experimental-windows`. This invokes
bounded native `NtQueryDirectoryFile` with per-entry handle-relative no-reparse
opens and real File IDs. **Even a completed, apparently conflict-free Windows
scan returns `WINDOWS_EXPERIMENTAL_UNVERIFIED` and exit 2.** Real Windows
NTFS/Junction/race acceptance remains operator-deferred; the examples below
are not evidence of that acceptance:

```bat
python scripts/inspect_queue_recovery_state.py --item-dir "D:\\private-workspace\\item"
python scripts/inspect_queue_recovery_state.py --item-dir "D:\\private-workspace\\itemA" --item-dir "D:\\private-workspace\\itemB"
python scripts/inspect_queue_recovery_state.py --item-dir "D:\\private-workspace\\item" --experimental-windows
```

Output is one JSON object, with only item ordinal numbers, fixed finding codes
and numeric counts. There are no filenames, directory paths, prompts,
responses, timestamps, file sizes, hostnames or credentials in the output.
A zero exit status indicates **no observed conflict in a completed, non-atomic
POSIX snapshot only**. Native Windows experimental scans **always exit 2**,
even when no conflicts were observed. Exit 2 indicates review required,
unverified native scan, unsafe entry, incomplete scan or invalid selection.
Neither exit code proves the work completed successfully.

The tool checks:
- duplicate TODO basenames across nested subdirectories (current dispatch
  flattens basenames);
- TODO/RUNNING overlaps and TODO/Success or RUNNING/Success basename overlaps;
- TODO and RUNNING pointing to the **same filesystem inode**, consistent with
  but not proof of an interrupted hardlink+unlink move;
- multiply linked queue entries;
- leftover `.success-*.tmp` files in the sibling
  `.success-publish-staging` tree, which could also be in-flight writes;
- symlinks, junctions and unsupported entries without following them.

A `POSSIBLE_INTERRUPTED_LINK_MOVE` is an observation only: no trusted
generation/lease, completed Worker call, writeback acknowledgement or retry
family is inferred. A `RUNNING_SUCCESS_OVERLAP` may be transient while the
Worker is still cleaning up, or may require operator recovery after a crash.
A `STAGING_TEMP_PRESENT` may be a normal in-progress staging link. Never
assume one of the two copies is disposable merely because they share an inode.

## Safety and limits

On supported POSIX environments the scan uses pinned directory file
descriptors opened with `O_DIRECTORY | O_NOFOLLOW` from the filesystem root,
opens child directories relative to verified parent descriptors, and enumerates
using `os.scandir(fd)`. It never opens file contents or follows symlinks.
**Any explicit `..` path segment is rejected before `abspath()`**,
preventing parent traversal from collapsing an unchecked symlink,
nonexistent ancestor or substituted path into an apparently clean scan.
The shared budget is enforced during enumeration, **before** buffering or
sorting children. It gets file identity through handle-relative
`os.stat(name, dir_fd=fd, follow_symlinks=False)`, not
`DirEntry.stat()` (which can return placeholder zero identities on Windows).
Unknown dev/inode/link-count fields are reported as `UNKNOWN_FILE_IDENTITY`
and never compared as real shared inodes. Windows junction/reparse entries
are unsafe; because safe descriptor-relative Windows traversal is not
provided, the whole inspection refuses Windows rather than opening them.

Unknown file types and absent/unsafe item roots produce fixed warnings without
leaking paths. It has a default cap of 10,000 directory entries per item;
exceeding this limit fails closed as `INCOMPLETE_OR_UNSAFE_SCAN`.
Use `--max-entries` to select a different cap up to 100,000 if required.
At most 100 item roots may be passed in one invocation.

The snapshot does **not** acquire any cross-process lock and is never atomic.
A path can be removed or replaced by a concurrent writer between metadata
calls, especially on Windows/SMB; results are diagnostic, not a validation
of quiescence or a safe replay decision. Restart only after human inspection
of original source/artifact lineage, run status, sink acknowledgement and
process state. No automatic cleanup or filesystem mutation is provided.

Hosted Linux regression tests use only synthetic temporary files and verify
real hardlinks, inode pairs, nested TODO names, completed-output conflicts,
staging leftovers, symlink refusal, bounded scans and output redaction.
Windows/SMB and actual Ollama/SQL/ES remain operator-deferred.
A future **separate** Windows implementation must use native no-follow
directory handles and reliable file IDs, with race and junction tests.
Neither this Linux acceptance gate nor a simulated Windows metadata test
claims a working Windows inspector.

## Phase 2f Windows native directory enumeration (not yet host accepted)

The opt-in Windows engine streams one `FILE_DIRECTORY_INFORMATION` record at a
time using `NtQueryDirectoryFile(ReturnSingleEntry=TRUE)` on pinned directory
handles. It validates fixed offsets, UTF-16 lengths and entry types, limits
the total entry count and depth, never follows reparse points, and opens each
child only via `NtCreateFile(RootDirectory=parent)` to query its full 128-bit
File ID and link count. Existing count-only JSON is reused; Windows basename
conflicts are compared case-insensitively. No filenames, raw errors, contents,
timestamps, paths or identities are printed. No file mutation is performed.

The native API behavior and NTFS races still require real Windows self-hosted
validation. No UNC/SMB support or path-based enumeration fallback exists;
a completed experimental scan is NOT a safe-replay or committed-writeback proof.
