# Windows native no-reparse handle identity groundwork (phase 2e)

This phase follows accepted queue inspection PR #261. It adds
`scripts/queue_win32_handle_identity.py` as a **separately scoped**
metadata-only primitive, without activating Windows in the production
`scripts/inspect_queue_recovery_state.py` CLI. That inspector still returns
`UNSUPPORTED_SAFE_SCAN_PLATFORM` on Windows by design.

## Why native handles are needed

Windows Python 3.10/3.11 `DirEntry.stat()` can return zero `st_ino`,
`st_dev`, and `st_nlink`, leading to false shared-inode claims. The new
`HandleIdentity` carries volume serial, 128-bit file ID, actual link count
and directory flag. It is process-private and is never logged, serialized or
read from file contents.

The implementation opens a drive root using Win32 `CreateFileW` with
`FILE_FLAG_OPEN_REPARSE_POINT` and `FILE_FLAG_BACKUP_SEMANTICS`. It walks
**one component at a time** through `NtCreateFile`, passing
`OBJECT_ATTRIBUTES.RootDirectory` as the already-opened parent handle,
`OBJ_DONT_REPARSE` and `FILE_OPEN_REPARSE_POINT`. It rejects reparse
attributes, junctions and symlinks and closes handles even on failure.
`GetFileInformationByHandleEx(FileIdInfo)` returns the full 128-bit ID;
`GetFileInformationByHandle` supplies the link count.

The code rejects drive-relative, UNC, extended/device namespace, parent
traversal (`..`), alternate data streams, trailing dot/space and unsupported
component forms before opening. Invalid IDs, unsupported filesystems and
metadata failures return fixed errors without source paths or credentials.

## Acceptance and commands

Synthetic Linux tests verify path refusals, structure width, correct
parent-handle selection and reverse cleanup (including failure). Real Windows
tests exercise temporary hardlinks, directory types and reparse refusal,
but Windows self-hosted CI is currently operator-deferred and **has not
executed** these new tests. There is no claim of real Windows acceptance.

Operator test (uses only temporary pytest directories):

```powershell
python -m pytest -q tests/prompt_pipeline/test_queue_win32_handle_identity.py
```

The primitive `probe_handle_identity(path, is_directory=False)` is not an
operator recovery command. It does not enumerate queue files, move/remove
anything, read prompt contents, or indicate a safe retry.

## Phase 2f still needed

A safe production scanner requires bounded native directory enumeration
**relative to pinned directory handles** (e.g. `NtQueryDirectoryFile`),
then verified no-follow child opens. Preserve the PR #261 fixed-code/count-only
output, no payload reads, and complete/unsafe fail-closed semantics. Windows
UNC/SMB directory handles, directory rename races and actual Windows
filesystem tests remain unverified. Do not enable the scanner by falling
back to pathname-based `os.walk` or `FindFirstFileW`.

References: [Microsoft NtCreateFile](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/nf-ntifs-ntcreatefile),
[FILE_ID_INFO](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_id_info),
[BY_HANDLE_FILE_INFORMATION](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/ns-fileapi-by_handle_file_information).
