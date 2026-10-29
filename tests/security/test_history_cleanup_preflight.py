"""Synthetic Git fixtures only: no real credentials, no real-history rewrite."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.history_cleanup_preflight import LEGACY_PATHS, preflight


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class PreflightTests(unittest.TestCase):
    def test_ref_lock_and_read_only_inventory(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            work = root / "work"
            work.mkdir()
            git(work, "init", "-b", "main")
            git(work, "config", "user.email", "fixture@example.invalid")
            git(work, "config", "user.name", "Fixture")
            keyfile = work / LEGACY_PATHS[0]
            keyfile.parent.mkdir(parents=True)
            keyfile.write_text("nonsecret fixture file\n", encoding="utf-8")
            git(work, "add", ".")
            git(work, "commit", "-m", "synthetic root")
            git(work, "branch", "older-snapshot")
            keyfile.unlink()
            (work / "README.md").write_text("current sanitized tree\n", encoding="utf-8")
            git(work, "add", "-A")
            git(work, "commit", "-m", "synthetic current")
            original = git(work, "rev-parse", "HEAD")
            git(work, "remote", "add", "origin", ".")
            git(work, "fetch", "origin", "+refs/heads/*:refs/remotes/origin/*")
            refs_before = git(work, "show-ref")
            result = preflight(original, cwd=work)
            self.assertEqual(result["remote_branch_count"], 2)
            self.assertEqual(result["known_paths_in_branch_heads"][LEGACY_PATHS[0]], 1)
            self.assertFalse(result["writes_git_references"])
            self.assertFalse(result["contains_secret_values"])
            self.assertEqual(refs_before, git(work, "show-ref"))
            with self.assertRaisesRegex(ValueError, "differs"):
                preflight("0" * 40, cwd=work)
            self.assertEqual(refs_before, git(work, "show-ref"))

    def test_synthetic_private_backup_restore_ref_shas(self):
        # Proves bundle/restore mechanics only on fake data; never bundle live CI repo.
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            work = root / "src"
            work.mkdir()
            git(work, "init", "-b", "main")
            git(work, "config", "user.email", "fixture@example.invalid")
            git(work, "config", "user.name", "Fixture")
            (work / "README.md").write_text("synthetic and safe\n", encoding="utf-8")
            git(work, "add", ".")
            git(work, "commit", "-m", "synthetic root")
            git(work, "branch", "legacy")
            bundle = root / "private-example.bundle"
            git(work, "bundle", "create", str(bundle), "--all")
            git(work, "bundle", "verify", str(bundle))
            restored = root / "restored.git"
            git(root, "clone", "--mirror", str(bundle), str(restored))
            self.assertEqual(
                git(work, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads"),
                git(restored, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads"),
            )

    def test_malformed_expected_sha_refused(self):
        for candidate in ("HEAD", "", "123", "a" * 41, "Z" * 40):
            with self.assertRaises(ValueError):
                preflight(candidate)


if __name__ == "__main__":
    unittest.main()
