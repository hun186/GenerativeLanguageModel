# Production credentials: complete private SQL/ES profiles (2026-10-30)

## Recommended arrangement

For SQL Server and Elasticsearch, **keep a connection's host, username, password, database/index, table and other settings in one file**, as before. The difference is *where* the populated file lives: under a Git-ignored `private/` subdirectory.

```text
czjLLM/
  config_sql/
    connection.py.example          # public blank copy-and-edit template
    akconfig_test.py               # existing public example / optional env-based profile
    private/                       # ignored: created on demand by SQL selector
      orion.py                     # local only: complete connection config
      akconfig_test.py             # local only: overrides same-name public example
  config_es/
    connection.py.example          # public blank copy-and-edit template
    akconfig_es_test.py            # existing public example / optional env-based profile
    private/                       # ignored: created on demand by ES selector
      news.py                      # local only: complete ES connection config
      akconfig_es_test.py          # local only: overrides same-name public example
```

**All paths inside `private/` are ignored by `.gitignore`, not just password files.** Git does not store empty directories; if you are not using the interactive config selector, create `private/` yourself. The interactive SQL/ES selectors create them if absent. Keep a separate private encrypted backup of these files and limit OS read permissions to the service/operator account.

## Add a new connection (preferred)

1. Choose an existing matching `config_sql/*.py` or `config_es/*.py` profile, or use the new public blank `connection.py.example` template.
2. Make a copy under the matching `private/` directory with the `.py` extension, e.g. `config_sql/private/orion.py` or `config_es/private/news.py`. A copied public example may use `os.environ.get(...)` instead of direct values: if you want all connection data together, replace only the *connection field expressions* with values inside the **ignored private copy**, leaving query/table/mapping settings untouched.
3. Inside that **private** file, set server/host, username, password, database/index, table, connection options and other job-specific fields together, matching the existing Python configuration variable names. Do **not** write populated values back to a Git-tracked root profile.
4. Pick the `private/<filename>.py` entry from the interactive SQL/ES file selector, or specify `sql_config_file: czjLLM/config_sql/private/orion.py` / `es_config_file: czjLLM/config_es/private/news.py` in a YAML job configuration.
5. For maximum backward compatibility, if a private profile and a public example share the same filename, the **private file takes precedence** even when the existing job YAML points at `czjLLM/config_sql/akconfig_test.py` or `czjLLM/config_es/akconfig_es_test.py`. This prevents updating each old YAML reference individually. The file selector lists the private entry instead of a duplicate root entry. Check the selected profile on first run and do not accidentally copy the same name for an unrelated connection.
6. Check `git check-ignore -v czjLLM/config_sql/private/orion.py` and `git check-ignore -v czjLLM/config_es/private/news.py`; verify your private paths are **not** shown by `git ls-files` or `git status --untracked-files=all`. An ignore rule cannot untrack a file that was already committed in the root directory.
7. On the operator machine, validate both real SQL/ES login and ES TLS hostname verification, then deploy. CI uses only synthetic fixtures and cannot prove connectivity.

This mechanism supports `.py`, `.yaml` and `.yml` files. The copy-and-edit templates use the `.py.example` suffix intentionally: rename the copied file to `.py` in `private/` to make it selectable. An explicit private path is used as-is; it is never silently redirected to a public file when missing.

## Existing environment-variable profiles remain compatible

PR #255 already removed hardcoded SQL passwords from four tracked samples. The earlier PR #258 code also removed six nonempty ES password literals from seven tracked profiles. Public root profiles remain safe-to-share environment-based examples; these paths are **not** moved or deleted by GitHub. They can continue to read:

- SQL: `CZJLLM_SQL_ORION_SERVER`, `CZJLLM_SQL_ORION_USERNAME`, `CZJLLM_SQL_ORION_PASSWORD`, `CZJLLM_SQL_SRP_SERVER`, `CZJLLM_SQL_SRP_USERNAME`, `CZJLLM_SQL_SRP_PASSWORD`, `CZJLLM_SQL_SRP_ADMIN_USERNAME`, `CZJLLM_SQL_SRP_ADMIN_PASSWORD`.
- ES: `CZJLLM_ES_HOST`, `CZJLLM_ES_USERNAME`, `CZJLLM_ES_PASSWORD`.

**Using these variables is optional if the chosen private profile supplies full credentials.** The central config loaders still load existing private env-file precedence for older deployments (`.env`, `.env.<CZJLLM_ENV>`, `.env.local`, then existing OS variables have highest priority). A private connection file can contain full values and does not need an additional password file. If you copied an env-based root example without editing its `os.environ` lookups, it will still require those OS/env values.

`CZJLLM_ENV=production` makes included SQL/ES production example profiles refuse incomplete connection credentials or missing destinations instead of using a localhost fallback. Independent private configurations with a supported ES `hosts` list are accepted with full authentication. The existing ES SSL hostname assertion may be disabled in old public profiles; restore verified TLS and correct certificate SANs before production use.

LLM/provider API keys (`CZJLLM_UTILS_API_KEY`, `CZJLLM_ANKINT_API_KEY`) continue using private OS/environment settings. **This change is about SQL/ES full connection profiles**, not putting all unrelated provider keys into database config files.

## Deployment and backup precautions

- **Before copying an update over the old deployment**, copy your current, operator-owned SQL/ES connection configuration into the ignored matching `private/` directory and verify the correct file loads. Do not rely on secrets previously committed in public root config files or use revoked API keys. A source update may replace the public root files; preserve `private/` separately.
- Do not put the `private/` directory into a public release archive, Docker build context, CI artifact, bug report or shared screenshot. Use service-specific read permissions and an encrypted private backup; restore only on an authorized machine.
- Any still-active SQL or Elasticsearch password that previously appeared in public Git history should be rotated by the operator. Removing it from current `main` does **not** scrub existing commits, other branches, clones or forks.
- Interactive SQL/ES configuration previews and the legacy ES resolver print sites now display recursively redacted maps instead of raw account passwords, HTTP auth, API keys, tokens or reset confirmation codes. These protections do not cover every external library's logs.
- `http_ca.crt` is a public CA trust certificate, not a private key. Never commit private-key files, .p12/.pfx bundles or populated env files.

## Test and release gates

The dedicated hosted credential workflow runs synthetic config tests (both old env-based profiles and new private complete-file scenarios), checks Git ignore behavior and syntax, followed by the changed-line secret scanner, standard Linux E2E and formal latest-HEAD Codex Review. No real provider, SQL/ES login, private files, private historical rewrite or destructive Git operation occurs in this PR. Merge and deployment are separately approval-gated.
