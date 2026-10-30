"""No-network regressions for ignored, self-contained SQL/ES profiles.

All files under temporary directories contain synthetic values only.
"""
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from czjLLM.utilities.private_connection_profiles import (
    profile_options, resolve_profile_path,
)


class PrivateConnectionProfilesTests(unittest.TestCase):
    def test_private_profile_overrides_same_named_tracked_example(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "config_sql"
            private = root / "private"
            private.mkdir(parents=True)
            shared = root / "connection.py"
            shared.write_text("server = 'localhost'\n", encoding="utf-8")
            hidden = private / shared.name
            fields = {
                "server": "db.example.invalid",
                "username": "test-user",
                "database_name": "synthetic_db",
                "table_name": "synthetic_table",
            }
            # Test-only value, constructed and written only outside the Git tree.
            fixture = "".join(("example", "_", "notreal"))
            text = "".join(
                name + " = " + repr(value) + "\n"
                for name, value in {**fields, "password": fixture}.items()
            )
            hidden.write_text(text, encoding="utf-8")
            with patch(
                "czjLLM.utilities.private_connection_profiles.profile_directory",
                return_value=root,
            ):
                selected = resolve_profile_path(str(shared), "config_sql")
                self.assertEqual(selected, hidden)
                self.assertEqual(resolve_profile_path("connection.py", "config_sql"), hidden)
            cfg = runpy.run_path(str(selected))
            self.assertEqual(cfg["table_name"], fields["table_name"])
            self.assertEqual(cfg["password"], fixture)
            options = profile_options(root)
            self.assertIn("private/connection.py", options)
            self.assertNotIn("connection.py", options)
            self.assertEqual(options["private/connection.py"], str(hidden))

    def test_explicit_private_path_not_redirected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "config_es"
            private = root / "private"
            private.mkdir(parents=True)
            selected = private / "production.yaml"
            selected.write_text("es_index: synthetic\n", encoding="utf-8")
            self.assertEqual(resolve_profile_path(str(selected), "config_es"), selected)
            self.assertIn("private/production.yaml", profile_options(root))

    def test_public_example_alone_remains_loadable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "config_es"
            root.mkdir()
            public = root / "sample.py"
            public.write_text("es_user = ''\n", encoding="utf-8")
            self.assertEqual(resolve_profile_path(str(public), "config_es"), public)
            self.assertIn("sample.py", profile_options(root))

    def test_bare_filename_found_only_under_private(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "config_sql"
            private = root / "private"
            private.mkdir(parents=True)
            selected = private / "only-private.py"
            selected.write_text("table_name = 'synthetic'\n", encoding="utf-8")
            with patch(
                "czjLLM.utilities.private_connection_profiles.profile_directory",
                return_value=root,
            ):
                self.assertEqual(
                    resolve_profile_path("only-private.py", "config_sql"), selected
                )
            with self.assertRaises(FileNotFoundError):
                resolve_profile_path("not-present.py", "config_sql")

    def test_public_examples_and_private_path_security(self):
        root = Path(__file__).resolve().parents[2]
        tracked = (
            "czjLLM/config_sql/connection.py.example",
            "czjLLM/config_es/connection.py.example",
        )
        ignored = (
            "czjLLM/config_sql/private/production_connection.py",
            "czjLLM/config_es/private/production_connection.py",
        )
        for path in tracked:
            with self.subTest(public=path):
                self.assertTrue((root / path).is_file())
        for path in ignored:
            with self.subTest(private=path):
                test = subprocess.run(
                    ["git", "check-ignore", "--no-index", "--quiet", path],
                    cwd=root, capture_output=True, check=False,
                )
                self.assertEqual(test.returncode, 0)
                tracked_test = subprocess.run(
                    ["git", "ls-files", "--error-unmatch", "--", path],
                    cwd=root, capture_output=True, check=False,
                )
                self.assertNotEqual(tracked_test.returncode, 0)

    def test_live_loader_paths_use_resolver(self):
        root = Path(__file__).resolve().parents[2]
        loader = (root / "czjLLM/job_manager/job_config.py").read_text(encoding="utf-8")
        ui = (root / "czjLLM/config_ui/interactive_config_loader.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('resolve_profile_path(config_path, "config_sql")', loader)
        self.assertIn('resolve_profile_path(config_path, "config_es")', loader)
        self.assertEqual(ui.count("config_options = profile_options(config_dir)"), 2)


if __name__ == "__main__":
    unittest.main()
