# 2026-10-29 public credential exposure remediation

This independent security PR is separate from queue correctness PR #254.

## Verified evidence (no raw secrets)

- Public repository: hun186/GenerativeLanguageModel.
- Legacy API key file: czjLLM/czjLLM_utils_key.py.
- Original commit prefix: 61590737dcc969cd.
- Public blob SHA: 35ca62a8181618612248e6e824b5a1cf8eb31d6f.
- Two complete key-style literals and four config_sql test files containing quoted passwords were identified.
- DeepSeek unusual usage on 2026-10-23 and 2026-10-24 remains under investigation. Key provider, request origins and unauthorized access have not been confirmed.

## Changes in this branch

- Remove the tracked legacy key module and read runtime CZJLLM_UTILS_API_KEY instead.
- Replace four SQL plaintext passwords with runtime environment reads:
  CZJLLM_SQL_ORION_PASSWORD, CZJLLM_SQL_SRP_PASSWORD and CZJLLM_SQL_SRP_ADMIN_PASSWORD.
- Ignore local legacy key file and private overrides; retain current environment sample without credentials.
- Keep existing detect-secrets hook and add a changed-lines pre-commit/Hosted CI gate.
- The incremental CI check is NOT a comprehensive historical scan. Never print detected secrets to CI logs.

## Mandatory operator follow-up

1. **Revoke** all potentially exposed provider keys; verify key IDs with provider support and provision fresh keys only in private secret stores. GitHub cannot tell whether a provider-side key is disabled.
2. Check SQL login validity and rotate any active database credentials; inspect access logs independently.
3. Examine full Git history, other branches, forks, public repositories, CI logs/artifacts and stored clones for exposure. Preserve evidence privately without copying literal keys.
4. Do not rewrite published Git history without explicit authorization and a coordinated migration plan. Source deletion does not purge published history or external clones.
5. Confirm runtime configuration and actual application startup in an operator-controlled environment. A missing env value must not silently select an old hardcoded credential.

## Local check

Run: python scripts/check_no_secrets.py --staged

Install local hooks with pre-commit install (requires pre-commit installed).

The scanner detects newly added high-risk literal key patterns, common credential assignments and private key headers. It is a guardrail, not proof that all secrets have been found.
