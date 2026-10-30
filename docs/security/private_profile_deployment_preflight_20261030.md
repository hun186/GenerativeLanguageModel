# SQL / Elasticsearch private connection profile: read-only deployment preflight

This phase follows accepted PR #258. GitHub `main` now contains 11 sanitized
`*.py.example` profiles, **not** the original live SQL/ES connection files.
The operator keeps complete local files, including host, username, password,
database/table/index and options, in:

- `czjLLM/config_sql/private/`
- `czjLLM/config_es/private/`

## Run locally after restoring your private backup

From the actual repository root:

```bash
python scripts/verify_private_connection_profiles.py
python scripts/verify_private_connection_profiles.py --kind sql
python scripts/verify_private_connection_profiles.py --kind es
python scripts/verify_private_connection_profiles.py --kind sql --profile akconfig_test.py
```

On Windows, use the same commands with `python` or the project's installed
Python executable. `--profile` accepts only a basename in the chosen
`private/` directory; legacy YAML file paths belong in the application
configuration, not this check.

Exit code **0** means the selected private directory contains at least one
supported profile and **every selected file** passed the read-only checks.
Exit code **2** means a missing file/directory, tracked or non-ignored file,
symlink, hardlink, unsafe extension/size, malformed Python, or required-field
presence/blank-literal issue. Output includes only generic finding codes and
anonymous ordinal profile numbers—not paths, hostnames, accounts or passwords.
The check is deliberately strict: one unsafe profile blocks a full-directory
check; select one named profile if you only wish to evaluate that file.

The checker uses Git's real index and ignore rules, rejecting both
`git ls-files` tracked entries and files not covered by `.gitignore`.
For Python files it parses AST without executing Python, validates presence
of SQL `server, username, password, database_name, table_name` or ES
`es_host/hosts, es_user, es_pass, es_index`, and detects blank literal
values. Dynamic expressions are not evaluated; a nonempty literal is not
proof that an account is valid. YAML files receive only ignore/path and
file-type checks; **YAML fields require manual validation** and this is
reported explicitly.

The checker **does not**:
- connect to SQL, ES or any LLM provider;
- execute user configuration Python, resolve environment variables or decrypt
  secrets;
- print actual connection values or full file paths;
- move, modify or delete files; perform Git history rewriting or rotate keys;
- prove TLS hostname verification, certificate SANs, account permissions,
  existence of database/tables/indices, or live credentials.

## Optional development-only anonymous Elasticsearch profile

The default preflight remains **strict**: both `es_user` and `es_pass`
must be populated when checking all ES profiles, so the original
`EMPTY_FIELD:es_user` / `EMPTY_FIELD:es_pass` report is not silently hidden.

If a **specific Python ES profile is intentionally anonymous** (both
`es_user` and `es_pass` explicitly blank), use the following opt-in
only after confirming that the target ES server is an authorized
development/test endpoint:

```bat
python scripts/verify_private_connection_profiles.py --kind es --profile YOUR_PROFILE.py --allow-anonymous-es
```

This opt-in must name **one** ES `.py` profile. It cannot be used for SQL,
all-profile checks, or YAML. To match the actual ES runtime validator, the
username may be a literal blank/whitespace-only string, but the password
must be a literal **empty string** or `None` (not spaces or tabs). A
whitespace-only password is treated as present by the runtime, so preflight
rejects that apparent anonymous pair. Dynamic expressions do not qualify for
the anonymous exception. `CZJLLM_ENV=production` / `prod` and
unrecognized environment names block it; production continues to require
both credentials. Partial ES authentication (only username or only password)
still fails. The ES host/hosts, index, syntax, Git-ignore and symlink
checks remain active. If the environment variable is unset, the flag is
still an explicit operator declaration of non-production intent; it does
**not** prove the server is actually isolated or anonymous access is safe.

To map an ordinal such as `PROFILE_4` to the local filename without
displaying file contents or credentials, run this in the repository root:

```bat
python -c "from pathlib import Path; p=Path('czjLLM/config_es/private'); f=sorted(x for x in p.iterdir() if x.suffix.lower() in ('.py','.yaml','.yml')); print(f[3].name)"
```

Keep anonymous access disabled on production and externally reachable ES,
and never set fake credentials to make the static check pass. A successful
opt-in result indicates only that the selected file's static checks passed,
**not** that the ES service permits or should permit anonymous login.
The usual unrestricted directory-wide preflight will still flag the
anonymous profile until its authentication policy is intentionally handled.

## Rollout

1. Confirm the backup exists outside the Git worktree; do not include it in
   ZIP/7z files intended for public sharing.
2. Update your source checkout to the merged PR #258 or later main.
3. Copy complete files into ignored local SQL/ES `private/` directories.
   Preserve filenames where old YAML references the original root file.
4. Run this checker. **Only after structural PASS**, run your actual SQL/ES
   authentication, query and ES TLS verification from the operator workstation;
   do not post passwords or connection output in GitHub review comments.
5. Retain a separate, encrypted backup. Historical Git objects may still
   contain old credentials; rotate any previously exposed but still valid
   SQL/ES accounts.

CI exercises this preflight against *synthetic* temporary Git repositories,
never against the operator's real `private/` folders. A Hosted PASS is
not a substitute for steps 3–4 on the deployment machine.
