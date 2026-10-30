# Local Windows NTFS queue scanner fixture acceptance (phase 2h)

Following the owner-approved #264 Squash Merge to main at
`d2b16f19a9703fc288850bb7855a3be331913704`, the GitHub-hosted
Windows 2022 native NTFS Python 3.10/3.11 tests and Linux E2E passed.
This is **GitHub-hosted evidence**, not the operator's own deployment.

## One click on a Windows machine

From an existing local checkout, double-click `run_windows_queue_ntfs_acceptance.bat`.
The batch file uses `.venv\Scripts\python.exe` if present or `python`
on PATH. Python **3.10 or 3.11** and **pytest already installed** are required.
The launcher never installs packages or accesses the internet. Offline
installations must provision approved dependencies in advance.

The launcher runs only the three checked-in native test suites on disposable
pytest temporary directories. It verifies NTFS file identity, hardlinks,
Junction safety, deterministic swap races and handle counts. One optional
directory-symlink privilege test can be skipped: a fixture PASS does not
mean every optional test ran.

Unique, no-overwrite JSON reports are written under
`%USERPROFILE%\queue-ntfs-acceptance-results`. Console and JSON include
fixed codes and names, with no local paths, prompts, fixture bytes,
credentials or test traceback. Test stdout/stderr are discarded.
Exit code 0 means **fixture tests PASS only**; exit 2 is REVIEW_REQUIRED.

For a custom location:

```powershell
python scripts/verify_windows_queue_ntfs_local.py --output-dir "$env:USERPROFILE\queue-ntfs-acceptance-results"
```

## Safety limits

No live queue path is accepted. No SQL/ES/LLM request, queue repair,
deletion, replay or recovery operation is performed. A local fixture PASS
does not prove the user's SMB/network filesystem, third-party concurrent
writers, sink acknowledgement, a durable source generation, or safe retry.
The default Windows scanner still refuses; explicit `--experimental-windows`
still requires review/exit 2. Do not change that safety gate based on
this report. Real production validation requires separate approval.

The GitHub-hosted Windows NTFS CI also executes the launcher. Linux
CI checks path-free, no-overwrite and fail-closed behavior only.

### Privacy-safe diagnostics

Each module records only the numeric total/skipped testcase count and
1-based failed testcase ordinal from a transient pytest JUnit file;
no case names, exception text, paths or test stdout/stderr enter the
report. `JUNIT_MISSING`, `JUNIT_INVALID` and `RUNNER_UNAVAILABLE_OR_TIMEOUT`
are fixed codes. The JUnit file stays in disposable temporary storage.
