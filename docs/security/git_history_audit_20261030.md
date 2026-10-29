# 2026-10-30 — Redacted historical credential exposure inventory

This is a non-destructive, source-backed security handoff after merged PR #255.
**DO NOT paste recovered credentials, passwords, token suffixes, or plaintext secrets into this repository, CI, PRs, issues, or support tickets.**

## Evidence and current status

- Repository: hun186/GenerativeLanguageModel (public).
- PR #255 squash merge/main: `3bb8a1693f834aef01c50c95158702406144f79f`.
- Removed API key source: `czjLLM/czjLLM_utils_key.py`. Earliest relevant root commit: `61590737dcc969cd44e87c4e66ebe5cbc4d54d68` (2025-09-12). Original blob SHA: `35ca62a8181618612248e6e824b5a1cf8eb31d6f`.
- Old root commit also tracked Python bytecode with credential-looking names, including `czjLLM/__pycache__/DeepSeek_utils_key.cpython-311.pyc` and `czjLLM/__pycache__/czjLLM_utils_key.cpython-311.pyc`. Bytecode can preserve constants and must be considered in cleanup.
- PR #254 old branch HEAD `4d8da5ad8e8bc465479025524077af5140362268` still has the removed key source. That branch is separate from accepted #255.
- GitHub Actions read-only historical audit run: https://github.com/hun186/GenerativeLanguageModel/actions/runs/40914086771 (SUCCESS on scanner commit `66932ecafb49596379821b2ae0a26441942645f8`).
- At that scan: 175 fetched remote branch HEADs, **171 still contain the legacy key source path**. Scan includes 176 fetched refs, 4,248 reachable blobs, 4,236 inspected blobs, 12 blobs omitted for being over 2 MB. 40 distinct blob objects matched at least one pattern: 4 key-style, 37 credential-assignment (categories can overlap); 3 compiled Python blob objects matched key-style patterns. These are artifact/pattern counts, **not distinct keys or verified credentials**.
- **Updated detection after formal Codex P2 remediation:** run https://github.com/hun186/GenerativeLanguageModel/actions/runs/40914674342 (SUCCESS on scanner HEAD `b52cfaa3923e86f5376d0f3baadbf1756a529ccf`) recognizes quoted credential keys in JSON, YAML and Python dictionaries. This broader detector inspected 4,241 of 4,253 reachable blobs; **144 matching blob objects**, including 141 credential-assignment and four key-style blob hits, with three matching compiled Python blobs; 12 oversize omissions remain. The earlier 40-match snapshot was an **undercount by the narrower detector**, not evidence that 104 new secrets appeared. Even this latest pattern count may contain false positives and duplicate secrets across versions.
- The scanner fetches the hosted branch heads and tags, and prints only aggregate counts. Actual source payloads are not printed, uploaded or persisted. Its regex patterns are not a full secret-auditing engine.
- Other public repositories were triaged by *current-tree filenames*, not full history/content; `hun186/menu-planner` currently tracks `.env` with a nonempty `MENU_ADMIN_KEY` (8 characters, value not reproduced). This may be stale/demo configuration; active authorization use is **not verified**. Treat as possible separate rotation/removal work, not confirmed unauthorized access.
- GitHub Actions inventory: >1,000 past workflow runs. Sampled eight run artifact listings returned no artifacts, but that is not an exhaustive artifact review. Two selected October 2026 job logs were readable and had no matching high-confidence key-style/password-assignments in the inspected text; attempted 2025 job logs returned 410 and could not be checked. No conclusion about all Actions logs is supported.

## Priority 0 — Contain before cleanup

1. Owner/operator: revoke every potentially exposed API key with the provider; verify key IDs/fingerprints only through secure provider tooling. Do **not** wait for repo cleanup to revoke.
2. Check SQL identities represented by four published test config files; rotate any active logins and review SQL audit/access logs independently.
3. Evaluate the separate public `menu-planner/.env` configuration; if used for authorization, rotate it and replace tracked configuration with a nonsecret example. Do not paste its current value anywhere.
4. Retain private screenshots, timestamps, original commit/blob identifiers, account support case numbers and provider findings without writing secrets. DeepSeek provider/request-IP attribution is still unconfirmed.

## Priority 1 — Complete evidence inventory

- Verify all 175 current branch heads, tags, PR head/merge refs, forks, local/external clones and release assets. Remote branch files and Git history must both be cleaned; a main-only rewrite is inadequate for the 171 branch heads.
- Perform independent high-coverage offline history and **working-tree** scans (e.g. locally installed and verified Gitleaks/TruffleHog, restricted output). Include bytecode, obsolete backups and larger files skipped in current 2 MB pattern-based scan. Distinguish true positives from tests and examples without revealing values in reports.
- Review remaining GitHub Actions logs and artifacts (including older or expired runs where recoverable) through authorized private storage. Avoid public report uploads containing findings.
- Confirm other accessible public repositories and all their branches/history; current-tree filename inspection alone cannot establish absence of secrets.
- Make a precise private revocation/replacement inventory and verify new runtime variables in an operator-controlled environment.

## Priority 2 — Approval-gated Git history rewrite plan

No history rewrite or destructive Git operation has been authorized or performed.

1. Require documented owner approval for exact repository, branch/tag scope, force-push timing and coordinator contacts. Freeze concurrent merges and pushes; especially reconcile PR #254 and any older branches.
2. Create restricted offsite backup of original refs plus a signed mapping of old/new commit IDs. Backups may themselves contain exposed secrets and must not be public.
3. Dry-run a fresh mirror clone with `git-filter-repo` or equivalent: remove committed key modules, secret-containing bytecode/cache and other confirmed secret-bearing paths across **all refs**, or substitute exact secret strings from a private, never-committed replacements file where preserving source is required. Take care not to delete sanitized current runtime configs or immutable audit evidence unintentionally.
4. Run an independent full-ref and checked-out-tree secret scan on the rewritten mirror. Test current app imports, SQL credential lookup, unit/E2E compatibility, GitHub workflows, PR #254 port/rebase, and expected release artifacts.
5. Coordinate branch/tag force pushes or retiring stale public branches *only after explicit approval*. Existing collaborator clones, local refs, forks, pull-request refs, cached archives, external copies and GitHub object retention may still reference old objects; Git history rewriting cannot guarantee global erasure.
6. Rebuild open PRs and CI from the cleaned base, confirm protections and secret push prevention, and notify affected collaborators to discard old refs safely. Preserve nonsecret incident audit records and verify provider-side revocation separately.

## Guarantees and limits

- PR #255 removed source literals from current main, **not from public history or 171 branch heads**.
- PR #256 is read-only scanner infrastructure; the report and process are evidence, not a credential-rotation receipt.
- Source snapshots, secret scanning findings and atypical DeepSeek usage do not independently establish which API key, IP, provider, or actor caused the usage.
