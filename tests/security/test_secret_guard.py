import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.check_no_secrets import added_lines, detect


class SecretGuardTests(unittest.TestCase):
    def test_key_format_detection(self):
        token = "sk" + "-" + "A" * 32
        self.assertIsNotNone(detect("token='" + token + "'"))

    def test_password_assignment_detection(self):
        sample = "pass" + "word = " + "'not_a_real_credential_123'"
        self.assertIsNotNone(detect(sample))

    def test_environment_variable_not_flagged(self):
        self.assertIsNone(detect('password = os.environ.get("SQL_PASSWORD")'))

    def test_diff_only_new_lines(self):
        patch = "+++ b/example.py\n-old = value\n+new = os.environ.get('SECRET')\n"
        self.assertEqual(list(added_lines(patch)), [("example.py", "new = os.environ.get('SECRET')")])

    def test_manual_latest_commit_range_scans_valid_parent(self):
        # workflow_dispatch defaults to HEAD^ when no base_sha is supplied.
        scanner = Path(__file__).resolve().parents[2] / "scripts" / "check_no_secrets.py"
        with tempfile.TemporaryDirectory() as folder:
            def git(*args):
                return subprocess.run(["git", *args], cwd=folder, check=True, capture_output=True, text=True)
            git("init")
            git("config", "user.email", "security-test@example.invalid")
            git("config", "user.name", "Security Regression")
            target = Path(folder) / "sample.txt"
            target.write_text("ordinary = 'first'\\n", encoding="utf-8")
            git("add", "sample.txt")
            git("commit", "-m", "initial")
            target.write_text("ordinary = 'second'\\n", encoding="utf-8")
            git("add", "sample.txt")
            git("commit", "-m", "next")
            checked = subprocess.run(
                [sys.executable, str(scanner), "--base", "HEAD^", "--head", "HEAD"],
                cwd=folder, capture_output=True, text=True,
            )
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertIn("PASS", checked.stdout)


if __name__ == "__main__":
    unittest.main()
