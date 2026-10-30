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
a TODO subdirectory. Windows paths may be quoted:

```bat
python scripts/inspect_queue_recovery_state.py --item-dir "D:\\private-workspace\\item"
python scripts/inspect_queue_recovery_state.py --item-dir "D:\\private-workspace\\itemA" --item-dir "D:\\private-workspace\\itemB"
```

Output is one JSON object, with only item ordinal numbers, fixed finding codes
and numeric counts. There are no filenames, directory paths, prompts,
responses, timestamps, file sizes, hostnames or credentials in the output.
A zero exit status indicates **no observed conflict in a completed, non-atomic
snapshot only**. Exit 2 means a conflict, unsafe entry, incomplete scan or
invalid CLI selection. Neither status proves that a run completed successfully.

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

The scan uses filesystem metadata (including `lstat` and link counts)
without opening file contents. It ignores directory and file symlinks rather
than following them. Unknown file types and absent/unsafe item roots produce
fixed warnings without leaking paths. It has a default cap of 10,000 directory
entries per item; exceeding this limit fails closed as `INCOMPLETE_OR_UNSAFE_SCAN`.
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
