"""Synthetic, no-network local migration tests."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

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
            field = "".join(("pass", "word"))
            source.write_text(field + " = " + repr(fake) + "\n", encoding="utf-8")

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

    def test_concurrent_new_private_file_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".gitignore").write_text(
                "czjLLM/config_sql/private/\\n"
                "czjLLM/config_es/private/\\n", encoding="utf-8"
            )
            subprocess.run(["git", "init", "-q"], cwd=root,
                           check=True, capture_output=True)
            directory = root / "czjLLM" / "config_sql"
            directory.mkdir(parents=True)
            src = directory / "akconfig_test.py"
            src.write_text("server = 'synthetic'\\n", encoding="utf-8")
            destination = directory / "private" / src.name
            real_link = os.link

            def publish_after_operator_intervenes(tmp, dst):
                # Simulate concurrent operator saving a newer connection file.
                Path(dst).write_text("new operator config", encoding="utf-8")
                return real_link(tmp, dst)

            with patch(
                "scripts.migrate_connection_profiles_to_private.os.link",
                side_effect=publish_after_operator_intervenes,
            ):
                with self.assertRaisesRegex(RuntimeError, "no overwrite"):
                    migrate(root, apply=True)
            self.assertEqual(destination.read_text(encoding="utf-8"),
                             "new operator config")
            self.assertEqual(src.read_text(encoding="utf-8"),
                             "server = 'synthetic'\\n")
            self.assertEqual(list(destination.parent.glob(".migrate-*")), [])

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
