"""Synthetic, no-network local migration tests."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.migrate_connection_profiles_to_private import migrate


class LocalMigrationTests(unittest.TestCase):
    def test_dry_run_copy_ignore_no_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".gitignore").write_text(
                "czjLLM/config_sql/private/\n"
                "czjLLM/config_es/private/\n", encoding="utf-8"
            )
            subprocess.run(["git", "init", "-q"], cwd=root,
                           check=True, capture_output=True)
            directory = root / "czjLLM" / "config_sql"
            directory.mkdir(parents=True)
            source = directory / "akconfig_test.py"
            fake = "".join(["synthetic", "-connection"])
            source.write_text("password = " + repr(fake) + "\n", encoding="utf-8")

            before = source.read_bytes()
            dry = migrate(root, apply=False)
            self.assertEqual(dry["would_copy"], 1)
            self.assertFalse((directory / "private").exists())

            applied = migrate(root, apply=True)
            self.assertEqual(applied["copied"], 1)
            dest = directory / "private" / source.name
            self.assertEqual(dest.read_bytes(), before)
            self.assertEqual(source.read_bytes(), before)
            dest.write_text("new private version", encoding="utf-8")
            again = migrate(root, apply=True)
            self.assertEqual(again["already_exists"], 1)
            self.assertEqual(dest.read_text(encoding="utf-8"),
                             "new private version")

    def test_never_copy_without_ignore_rule(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".gitignore").write_text("\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=root,
                           check=True, capture_output=True)
            directory = root / "czjLLM" / "config_sql"
            directory.mkdir(parents=True)
            (directory / "akconfig_test.py").write_text(
                "server = 'synthetic'\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(RuntimeError, "Git ignored"):
                migrate(root, apply=True)
            self.assertFalse((directory / "private").exists())


if __name__ == "__main__":
    unittest.main()
