# Git history cleanup: approval-gated, reversible plan (2026-10-30)

**Status: planning and read-only preflight ONLY. No public history rewrite, force push, branch deletion, tag update or credential revocation is performed.**

## Verified background

- #255 removed previously committed key material from current `main` source; #256 added read-only historical scans.
- The latest verified #256 scan counted 175 fetched remote branch heads, **171** still containing the legacy `czjLLM/czjLLM_utils_key.py` path, **144** credential-pattern matching blob objects (not distinct verified secrets), and **12** blobs larger than the scan limit. Prior root Git history also includes two credential-related compiled `.pyc` files.
- Four formerly plaintext SQL test configs were sanitized on current `main`; a rewrite that deletes those paths wholesale may break current code. Historical literals need privately sourced targeted replacement instead.
- #254 is still an independent OPEN queue-correctness PR; its old branch and exact-head review cannot be carried over as-is after a history rewrite.
- Provider-side revocation of potentially exposed keys and actual DeepSeek attribution remain unverified.

## Scope of this PR: safe preflight

`scripts/history_cleanup_preflight.py --expected-main <40-character main SHA>` uses only read-only Git commands. It compares the fetched remote `main` SHA to an explicit frozen value and fails closed on mismatch. It counts **branch HEAD path presence** for the known legacy key source, two compiled files and four SQL test configs; records the fetched branch-head count, tag count, and a SHA256 digest of sorted fully qualified remote branch **and fetched tag** refnames/object IDs (schema v2; annotated tag objects retain their own identity). It reads no credential content, writes no refs and produces redacted aggregate JSON only.

`.github/workflows/security-history-cleanup-preflight.yml` fetches remote branch heads/tags with `contents: read` and no persisted checkout credentials, runs synthetic Git unit tests, then executes that read-only preflight. A PR run uses its event base SHA; a manual run requires an explicit SHA input. The hosted run must **fail** if `main` has changed since the locked snapshot. A successful run establishes only this snapshot's path-presence counts, not completeness of historical credential scanning. Digest semantics changed from schema v1 (branches only) to v2 (branches plus tags); **old v1 digest values must not be compared with v2 digests**. Full fetch and frozen ref scope are mandatory; pull-request refs, forks and inaccessible refs remain excluded.

The synthetic tests exercise stale-SHA refusal, real two-branch read-only inventory, tag retargeting and annotated-tag object replacement (both must change the digest without changing tag count), and a `git bundle` / `git clone --mirror` backup-restore demonstration **on synthetic files only**. No backup of actual exposed bytes is generated or published by CI.

## Approved sequence still required before destructive action

### Gate 0 — credential containment, freeze and confidential scope

1. Owner revokes all potentially exposed API keys at their providers, and rotates any SQL credentials still valid. Preserve source IP and usage evidence in provider-controlled records. Neither GitHub nor this script can revoke or identify unauthorized callers.
2. Freeze collaborators' pushes and deployments **only when the cleanup execution window has been approved**. Build a private inventory of all branches, tags, deleted refs where recoverable, `refs/pull/*` where accessible, forks/clones and release/Actions assets. Reconcile pending PR #254.
3. Capture exact SHA for `main`, every branch/tag ref, UTC cutoff, SHA snapshot digest, owners, and branch-protection/CI settings. Any mismatch invalidates approval and triggers a fresh scan.

### Gate 1 — private verified backup and recovery drill

1. On a separately secured operator machine, clone full mirrored Git history into protected storage. Make an encrypted/offline private bundle with restrictive ACLs. **That backup still contains exposed credentials. Never upload it as a public GitHub artifact, commit, or attached ticket.**
2. Verify `git bundle verify`, independent `git clone --mirror` restoration, `git fsck --full`, and exact branch/tag ref-to-SHA equality against a separate private manifest. Store checksum, tools/versions and old SHA mapping securely. Tests in this PR demonstrate the mechanism on **synthetic** history only.
3. A public rollback would restore old refs containing exposed secrets, potentially re-exposing them. It requires independent emergency authorization and is *not* equivalent to securing revoked credentials. Have a rebuild-from-clean-base alternative.

### Gate 2 — offline, detached rewrite rehearsal

1. Work on a **throwaway mirror** restored from the private backup in an isolated environment. Remove Git remotes and disable hooks/automatic deployment before running an operator-reviewed and version-pinned `git-filter-repo`. This PR does not invoke a rewrite tool against actual history.
2. Candidate removal scope: the known legacy key source and confirmed key-bearing bytecode artifacts across all refs. Audit for other sensitive compiled caches. For four SQL config files, do **not** delete sanitized working source; replace historical secret bytes using a tightly controlled, never-committed private replacements file (never put values on the command line, public logs, PR or CI).
3. Generate and privately encrypt the complete old/new SHA mapping. Verify every branch/tag/ref, no known exposed paths still reachable, current sanitized main intact, `git fsck`, an independent full-size/binary secret scan (e.g. verified Gitleaks/TruffleHog with restricted output), app imports/configs, Linux E2E, releases and workflows. The current regex history scanner's 2 MB cap and false positives prevent a full clearance claim.
4. Rebase/reconstruct #254 on the rewritten history and obtain new review, tests and hosted CI; old SHA-based approval evidence is invalid after rewrite.
5. Restore the pre-rewrite synthetic/isolated backup to another local mirror, verify old ref mapping and operator recovery procedure. No test should publish those refs to GitHub.

### Gate 3 — separate explicit approval for any remote changes

Before any force push, tag or branch deletion, owner must approve an exact set of affected repository refs, snapshot SHA/digest, private backup-restore evidence, secret-scan findings, freeze window, maintainers/consumers to notify, CI and deployment restart plan, GitHub Support request for cached/pull refs, #254 recovery plan and rollback roles. Only then could an operator execute those commands. **This PR carries no authorization to do so.**

## Residual risks

GitHub history objects, forks, pull-request refs, local clones, cached code, release assets and external archives may retain exposed bytes after a rewrite; provider-side revocation remains mandatory. This preflight inventories current remote branch-head paths, not all secrets or all past objects. It does not scan old GitHub Actions logs/artifacts, all forks, deleted/unreachable refs or large blob bodies.
