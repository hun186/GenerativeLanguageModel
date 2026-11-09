# Linux local Queue fixture acceptance — one command

The operator currently plans to run GenerativeLanguageModel on either a
**Windows local NTFS disk** or a **Linux workstation local filesystem**.
Windows already has `run_windows_queue_ntfs_acceptance.bat`.
This is the matching Linux **disposable offline fixture** acceptance entry.
SMB is deferred; neither launcher authorizes shared-network Queue replay.

## Operator command (when a Linux workstation is available)

From an already approved repository checkout:

```bash
bash run_linux_queue_local_acceptance.sh
```

The launcher selects `.venv/bin/python` when executable, or `python3`
from PATH. Python 3.10/3.11 and pytest plus the installed project dependencies
are required. It **does not install dependencies, access the network,
accept live paths, prompt for credentials or call an LLM / SQL / ES sink**.

The pytest child explicitly uses `--noconftest` as well as disabled plugin
autoload: repository conftest files must not import local LLM credential
settings. The source checkout must have no tracked or nonignored untracked
changes; use an isolated clean checkout rather than modifying a production
working directory if necessary.

It invokes only a fixed checked-in Linux acceptance fixture suite:
`tests/prompt_pipeline/test_queue_linux_local_fixture.py`.
That suite creates its own ephemeral files under Linux `/tmp` and checks
native inode/hardlink/no-follow identity, no-clobber RUNNING→TODO behavior
on collision, non-conflicting requeue, and safe **read-only** inspection
including refusal of symlink traversal. It never touches a real Queue.

## Report / result semantics

- Reports: `~/queue-linux-acceptance-results/queue_linux_fixture_<unique>.json`.
- Reports are private (`0700` directory and `0600` files), append-only
  per invocation / exclusive creation, and contain only fixed codes, safe
  numeric JUnit test totals, failed ordinals and source commit identity.
- The output directory must be owned by the invoking user and private.
  Symlinks, permissive directories, missing files, zero executed tests,
  skips, failing cases, unsupported Python, missing pytest, unavailable
  safe temporary storage or dirty/unknown Git revision (including any
  nonignored untracked file) are
  **REVIEW_REQUIRED**; no permissive fallback.
- Exit 0 means **FIXTURE_PASS_ONLY**.
  Exit 2 means **REVIEW_REQUIRED**.
- Regardless of fixture PASS, `deployment_status` is always
  **NOT_VERIFIED**; it is not a production release gate by itself.

The checked-in tests and runner are also exercised in GitHub-hosted
Ubuntu CI. That proves **Hosted** fixture behavior only, not the actual
Linux workstation filesystem, actual operator run state, runtime memory,
LLM responses or sink readback.

## Still requiring a separate operator-controlled release gate

- Real local Windows/Linux interrupted-run safe manual rerun/resume,
  intact original sources, TODO/RUNNING/Success generation conflicts,
  and correct incomplete-vs-success bookkeeping.
- Independent SQL/ES stored-result readback and idempotent writeback
  behavior when those sinks are configured.
- No automatic replay, repair, deletion, worker force-kill or credentials
  access is permitted by this fixture report.
- SMB/concurrent network writers are **deferred**, not falsely marked PASS.

Track actual operator-owned evidence in
[Issue #266](https://github.com/hun186/GenerativeLanguageModel/issues/266).
Do not post private paths, prompts or credential-bearing stdout into the issue.
