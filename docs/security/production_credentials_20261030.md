# Production credentials and shareable examples (2026-10-30)

## Inventory / scope

- **SQL Server:** Four tracked `czjLLM/config_sql/akconfig_test*.py` profiles previously contained quoted passwords. PR #255 moved their passwords to `CZJLLM_SQL_ORION_PASSWORD`, `CZJLLM_SQL_SRP_PASSWORD` and `CZJLLM_SQL_SRP_ADMIN_PASSWORD`. All four now also read service-specific `CZJLLM_SQL_ORION_SERVER`, `CZJLLM_SQL_ORION_USERNAME`, `CZJLLM_SQL_SRP_SERVER`, `CZJLLM_SQL_SRP_USERNAME` and `CZJLLM_SQL_SRP_ADMIN_USERNAME` instead of public production hosts or identities. Table/database names remain shareable metadata. Independently confirm whether old SQL credentials are still valid.
- **Elasticsearch:** Six tracked `czjLLM/config_es/akconfig_es_*.py` profiles had a nonempty `es_pass` literal; a seventh profile had an empty string. **All seven** now read `CZJLLM_ES_HOST`, `CZJLLM_ES_USERNAME` and `CZJLLM_ES_PASSWORD` from the operator's private runtime environment. Default host is local-only `http://localhost:9200`; no stored password or production URL remains in these profile assignments. These changes can affect existing operator deployments; configure ES before updating.
- **LLM providers:** Previous legacy `czjLLM_utils_key.py` was removed on current `main` by PR #255. `CZJLLM_UTILS_API_KEY` is its runtime replacement. The model pool already supports `CZJLLM_ANKINT_API_KEY`; do not commit populated examples. Provider ownership, active validity and revocation require independent verification.
- **CA certificate:** Tracked `http_ca.crt` is a public trust certificate, not itself an API password/private signing key; do not place private keys or client identity bundles in Git.
- **Other findings:** Prior history audit counted matching *Git blob objects*, not unique verified live credentials; it is not an exhaustive inventory of current or historical secrets. This PR does **not** rewrite old Git objects or invalidate exposed credentials.

## Operator setup

1. Set and verify `CZJLLM_ENV=production` in the actual service environment **before** startup. Use a service/OS secret manager where possible. For local debugging only, copy the blank `czjLLM/env_examples/czjllm.env.example` to an ignored `.env.production` at the repository root. Never commit the populated file.
2. Set `CZJLLM_ES_HOST` (HTTPS URL and certificate matching the hostname for production), `CZJLLM_ES_USERNAME` and `CZJLLM_ES_PASSWORD`. The same ES credentials are used by these seven shareable source profiles. If differing ES clusters/accounts are required, run each job with a separate private environment or use a private ignored `*_local.py` profile rather than hard-coding new credentials.
3. Set the appropriate SQL server, username and password variables for each service profile. ORION uses the `CZJLLM_SQL_ORION_*` variables, SRP uses `CZJLLM_SQL_SRP_*`, and the legacy SRP admin profile uses `CZJLLM_SQL_SRP_ADMIN_USERNAME` and `CZJLLM_SQL_SRP_ADMIN_PASSWORD`. A production profile with missing SQL authentication fields fails closed. The operator must configure runtime values; plaintext credentials are not included here.
4. Set `CZJLLM_UTILS_API_KEY` and `CZJLLM_ANKINT_API_KEY` only if those providers/features are used. Ensure revoked old keys are not copied into private runtime files.
5. The central SQL/ES config-file loaders call the existing `load_czjllm_env_files_once` helper before importing profiles. Values in the actual OS process environment take precedence over private files: `.env` then `.env.<CZJLLM_ENV>` then `.env.local`. Directly importing a profile bypasses this loader: then set OS environment variables explicitly. The helper loads only once per process.
6. Credential fields are masked during interactive configuration previews, and incomplete ES username/password pairs now raise an error. SQL source profiles require a complete server/username/password set in production rather than attempting interactive prompts. These checks are **not** proof of real database connectivity.
7. For production TLS, retain certificate verification and use an ES certificate with a matching DNS/IP Subject Alternative Name. Some existing source profiles still set `es_ssl_assert_hostname=False` for historical compatibility; **do not assume this provides hostname verification**. Review TLS policy separately before relying on Internet-exposed ES endpoints.

## Local/private settings excluded by Git

`.env`, `.env.*`, any `*_local.py` or `*_private.py` connection override inside `config_es/` or `config_sql/`, directories named `secrets/`, and private-key containers are ignored. Public blank `.env.example` files remain committable. **Ignore rules do not untrack existing Git files or remove historical versions.**

Never publish populated `.env` files, example credentials, decoded tokens, SQL connection strings, secret fingerprints, certificates containing private keys or incident screenshots. The production operator must rotate any *other* still-valid SQL/ES credentials exposed in historical source independently.

## Verification and roll-out

- First verify static source/test gates and exact PR HEAD on Hosted GitHub (secret scan, synthetic credential/unit tests, Linux E2E, formal Codex review). Production SQL and ES tests are **operator-deferred**, not simulated as successful.
- Before deploying this PR, take an inventory of the actual ES hostname and account, validate that private runtime values are available to the process, verify login and TLS on staging, then restart the relevant job or service. Avoid inserting credentials in console output.
- If operator staging fails, restore the previous **runtime configuration**, not the historically exposed plaintext password. Do not commit or redistribute old values for rollback.

**Fail-closed production host rule:** the development-only `localhost` fallback applies only when `CZJLLM_ENV` is not `production` or `prod`. With production selected, an unset ES/SQL host is considered missing rather than silently connecting to localhost. No credential value or actual production connection is tested in hosted CI.
