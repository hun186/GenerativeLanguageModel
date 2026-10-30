# Windows NTFS real-host acceptance for queue diagnostics (phase 2g)

## Scope and safety guarantee

This is a real Windows acceptance **test harness**, not an operator recovery
procedure or permission to enable automatic retry. Production command
`scripts/inspect_queue_recovery_state.py` continues to refuse default Windows
inspection. Even when an explicit `--experimental-windows` probe completes,
`WINDOWS_EXPERIMENTAL_UNVERIFIED` and process exit 2 still require review.
No files are replayed, deleted or written by the inspector.

After merged PR #263 (`4fbb9e5ad5c1f3a1455d7a506bd574d67e52b261`),
`.github/workflows/ci.yml` adds `windows-native-ntfs-hosted` matrix
Python 3.10/3.11 on **GitHub-hosted Windows 2022**, independent of the existing
operator-owned `windows-selfhosted` runners. Each matrix job must finish
`SUCCESS` before claiming Windows/NTFS native acceptance on that hosted
environment. A queued self-hosted runner is not a successful test.

## Real NTFS probes

`tests/prompt_pipeline/test_queue_win32_ntfs_acceptance.py` creates all
fixtures under pytest's disposable `tmp_path`. It verifies:

- Actual NTFS filesystem preflight, native File ID (128-bit), volume serial,
  link count and metadata-only file probing.
- TODO/RUNNING hardlink cross-role identity and copy-free payload preservation,
  case-insensitive basename collision without falsely shared identity, and
  staging residue not counted as Success.
- Default Windows refusal, experimental-only explicit activation, fixed
  status/exit 2, item-ordinal/count/code-only JSON without filenames or source
  bytes.
- Child junction, junction substituted for a top-level role, and junction
  substituted for an ancestor; no accidental traversal into outside fixture.
- Deterministic race: after native directory metadata enumeration but before
  the child Handle is opened, replace the child directory by a junction and
  require fail-closed incomplete result rather than following the target.
- Deliberate enumeration cap and 45 consecutive native scans with process
  handle-count leak check.

Temporary junctions are removed through `os.rmdir` only. If the Windows test
host cannot create a junction, test setup **fails**, rather than quietly
marking the security acceptance as skipped. Linux runs cannot substitute for
these tests; Windows-native tests are skipped on POSIX.

## Operator / CI procedure

Read `.github/workflows/ci.yml` results for
`windows-native-ntfs-hosted (3.10)` and `(3.11)`. These are isolated tests
with no repository deployment secrets, real SQL/ES/LLM calls or production queue.

On an operator-owned **disposable** NTFS test workspace with the full
repository and pytest dependencies available:

```powershell
python -m pytest -q tests/prompt_pipeline/test_queue_win32_handle_identity.py tests/prompt_pipeline/test_queue_win32_native_enumeration.py tests/prompt_pipeline/test_queue_win32_ntfs_acceptance.py --maxfail=1
```

Do not use a live queue directory to run these tests. The tests generate and
delete only their own temporary fixtures. Do not disable or bypass Windows
experimental review gating after this PR automatically.

## Acceptance boundaries

GitHub-hosted Windows/NTFS test success would be evidence only for the
temporary host's native API behavior and tested race scenarios. The actual
user's Windows host, different drive/filesystem and Windows/SMB network shares
are **not covered**. Concurrent third-party writers, true OS interruption,
file-system filters, cross-process crash-safe source generations, durable SQL/ES
sink acknowledgement and authorization to recover/retry remain unverified.
Actual Windows runner failure must be investigated rather than treated as a
Linux-synthetic equivalent. Formal exact-head Codex Review, CI, and explicit
user authorization are required before Merge.

## First hosted Windows results and Codex P2 hardening

The first CI on initial PR #264 HEAD `d4f8da6b752b6a0eab5e69a7a4cc20fdaade5892`
reported **SUCCESS** for both hosted Windows 2022 Python 3.10 and 3.11 jobs
in run `41052426467`. It also passed the NTFS prerequisite. This is real
native Windows evidence, but **not final acceptance of the subsequent
changes**. Formal Codex Review identified one P2: `cmd.exe /c mklink /J`
interpreted metacharacters in temporary directory names. The new test helper
transfers path strings only via UTF-8 JSON encoded as Base64 inside
PowerShell's `-EncodedCommand` (UTF-16LE), with no user-controlled raw shell
text; an additional real NTFS test uses `&`, `%`, `^`, `!` and `$` in
temporary path components. New exact-head hosted Windows jobs and Codex
re-review must pass before claiming this hardening accepted.
