"""No-network regression coverage for value-free private profile preflight."""
from pathlib import Path
import contextlib
import io
import os
import subprocess
import sys
from unittest.mock import patch
import tempfile
import unittest

from scripts.verify_private_connection_profiles import check_one, inspect, main
from czjLLM.utilities.credential_config import validate_es_config


def synthetic_root(tmp: str) -> Path:
    root = Path(tmp)
    (root / ".gitignore").write_text(
        "czjLLM/config_sql/private/\nczjLLM/config_es/private/\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=root,
                   capture_output=True, check=True)
    for folder in ("config_sql", "config_es"):
        (root / "czjLLM" / folder / "private").mkdir(parents=True)
    return root


class PrivateDeploymentPreflightTests(unittest.TestCase):
    def test_checks_complete_profiles_without_echoing_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = synthetic_root(tmp)
            marker = "".join(("not", "-a-", "real-credential"))
            sql = root / "czjLLM/config_sql/private/example.py"
            es = root / "czjLLM/config_es/private/example.py"
            sql.write_text(
                "\n".join((
                    'server = "example.invalid"',
                    'username = "operator"',
                    'password = ' + repr(marker),
                    'database_name = "synthetic"',
                    'table_name = "synthetic"',
                )) + "\n", encoding="utf-8",
            )
            es.write_text(
                "\n".join((
                    'es_host = "https://example.invalid:9200"',
                    'es_user = "operator"',
                    'es_pass = ' + repr(marker),
                    'es_index = "synthetic"',
                )) + "\n", encoding="utf-8",
            )
            summary, issues = inspect(root)
            self.assertEqual(issues, [])
            self.assertEqual(summary["sql"]["checked"], 1)
            self.assertEqual(summary["es"]["checked"], 1)
            self.assertNotIn(marker, repr(summary) + repr(issues))

    def test_private_missing_is_blocked_not_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = synthetic_root(tmp)
            result, issues = inspect(root)
            self.assertEqual(result["sql"]["profiles"], 0)
            self.assertIn("sql:NO_PRIVATE_PROFILE", issues)
            self.assertIn("es:NO_PRIVATE_PROFILE", issues)

    def test_structural_fields_and_blank_values_are_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = synthetic_root(tmp)
            p = root / "czjLLM/config_sql/private/example.py"
            p.write_text(
                "server = ''\nusername = 'person'\n"
                "password = None\ndatabase_name = 'test'\n",
                encoding="utf-8",
            )
            issues = check_one(root, p, "sql")
            self.assertIn("MISSING_FIELD:table_name", issues)
            self.assertIn("EMPTY_FIELD:server", issues)
            self.assertIn("EMPTY_FIELD:password", issues)
            self.assertNotIn("person", str(issues))

    def test_es_hosts_precedence_and_missing_annassign(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = synthetic_root(tmp)
            p = root / "czjLLM/config_es/private/example.py"
            p.write_text(
                "es_host = ''\nhosts = ['https://example.invalid:9200']\n"
                "es_user = 'operator'\nes_pass = 'dummy'\n"
                "es_index = 'synthetic'\n", encoding="utf-8",
            )
            self.assertEqual(check_one(root, p, "es"), [])
            p.write_text(
                "es_host = ''\nhosts = []\n"
                "es_user = 'operator'\nes_pass = 'dummy'\n"
                "es_index: str\n", encoding="utf-8",
            )
            issues = check_one(root, p, "es")
            self.assertIn("EMPTY_FIELD:es_host", issues)
            self.assertIn("EMPTY_FIELD:es_index", issues)

    def test_syntax_failure_does_not_echo_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = synthetic_root(tmp)
            marker = "".join(("private", "-", "fixture", "-value"))
            p = root / "czjLLM/config_es/private/example.py"
            p.write_text("es_pass = " + repr(marker) + "\ninvalid = (\n",
                         encoding="utf-8")
            errors = check_one(root, p, "es")
            self.assertEqual(errors, ["INVALID_PYTHON_SYNTAX"])
            self.assertNotIn(marker, repr(errors))

    def test_ignored_but_tracked_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = synthetic_root(tmp)
            path = root / "czjLLM/config_sql/private/example.py"
            path.write_text(
                "server = 'x'\nusername = 'x'\n"
                "password = 'x'\ndatabase_name = 'x'\ntable_name = 'x'\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "-f", str(path.relative_to(root))],
                           cwd=root, capture_output=True, check=True)
            issues = check_one(root, path, "sql")
            self.assertIn("STILL_TRACKED", issues)

    def test_private_file_symlink_is_rejected(self):
        if not hasattr(os, "symlink"):
            self.skipTest("No symlink support")
        with tempfile.TemporaryDirectory() as tmp:
            root = synthetic_root(tmp)
            source = root / "outside.py"
            source.write_text("server = 'synthetic'\n", encoding="utf-8")
            p = root / "czjLLM/config_sql/private/example.py"
            try:
                p.symlink_to(source)
            except (OSError, NotImplementedError):
                self.skipTest("Symlinks unavailable on this machine")
            self.assertEqual(check_one(root, p, "sql"),
                             ["SYMLINK_NOT_ALLOWED"])

    def test_symlinked_connection_directory_is_rejected(self):
        if not hasattr(os, "symlink"):
            self.skipTest("No symlink support")
        with tempfile.TemporaryDirectory() as tmp:
            root = synthetic_root(tmp)
            src = root / "czjLLM" / "config_sql"
            outside = root / "moved-sql"
            src.rename(outside)
            try:
                src.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("Directory symlinks unavailable")
            _, issues = inspect(root, kind="sql")
            self.assertIn("sql:PRIVATE_DIRECTORY_SYMLINK", issues)

    def test_cli_returns_failure_without_leaking_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = synthetic_root(tmp)
            path = root / "czjLLM/config_sql/private/example.py"
            marker = "".join(("no", "-", "credential", "-", "output"))
            path.write_text(
                "server='example.invalid'\nusername='u'\npassword="
                + repr(marker) + "\ndatabase_name='demo'\ntable_name='demo'\n",
                encoding="utf-8",
            )
            out = io.StringIO()
            with patch.object(sys, "argv", ["preflight", "--root", str(root),
                                           "--kind", "sql"]):
                with contextlib.redirect_stdout(out):
                    result = main()
            self.assertEqual(result, 0)
            self.assertIn("No connection made", out.getvalue())
            self.assertNotIn(marker, out.getvalue())
            self.assertNotIn(str(root), out.getvalue())

    def test_yaml_is_not_executed_or_claimed_semantically_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = synthetic_root(tmp)
            p = root / "czjLLM/config_es/private/example.yaml"
            p.write_text("es_pass: synthetic\n", encoding="utf-8")
            result, issues = inspect(root, kind="es")
            self.assertEqual(issues, [])
            self.assertEqual(result["es"]["yaml_manual"], 1)
            self.assertEqual(result["es"]["checked"], 1)

    def test_single_profile_must_be_basename_and_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = synthetic_root(tmp)
            for selection in ("../outside.py", "private/name.py", "/tmp/file.py"):
                result, issues = inspect(root, kind="sql", profile=selection)
                self.assertEqual(result, {})
                self.assertEqual(issues, ["INVALID_PROFILE_SELECTION"])
            result, issues = inspect(root, kind="both", profile="example.py")
            self.assertEqual(result, {})
            self.assertEqual(issues, ["INVALID_PROFILE_SELECTION"])

    def test_anonymous_es_is_strict_by_default_and_explicit_in_development(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = synthetic_root(tmp)
            p = root / "czjLLM/config_es/private/anon.py"
            p.write_text('''es_host = "http://localhost:9200"
es_user = ""
es_pass = ""
es_index = "synthetic_index"
''', encoding="utf-8")
            with patch.dict(os.environ, {"CZJLLM_ENV": "development"}):
                strict, strict_issues = inspect(root, kind="es", profile="anon.py")
                self.assertEqual(strict["es"]["checked"], 0)
                self.assertIn("es:PROFILE_1:EMPTY_FIELD:es_user", strict_issues)
                self.assertIn("es:PROFILE_1:EMPTY_FIELD:es_pass", strict_issues)
                allowed, issues = inspect(
                    root, kind="es", profile="anon.py", allow_anonymous_es=True
                )
                self.assertEqual(issues, [])
                self.assertEqual(allowed["es"]["checked"], 1)
                # Broad scan remains strict even when one profile is anonymous.
                _, broad = inspect(root, kind="es")
                self.assertIn("es:PROFILE_1:EMPTY_FIELD:es_user", broad)

    def test_partial_es_auth_never_bypasses_even_with_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = synthetic_root(tmp)
            p = root / "czjLLM/config_es/private/anon.py"
            with patch.dict(os.environ, {"CZJLLM_ENV": "dev"}):
                for user, password, missing in (
                    ("", "synthetic", "es_user"),
                    ("synthetic", "", "es_pass"),
                ):
                    with self.subTest(missing=missing):
                        p.write_text(
                            "es_host='http://localhost:9200'\n"
                            "es_user=" + repr(user) + "\n"
                            "es_pass=" + repr(password) + "\n"
                            "es_index='synthetic'\n", encoding="utf-8"
                        )
                        _, issues = inspect(
                            root, kind="es", profile="anon.py",
                            allow_anonymous_es=True,
                        )
                        self.assertIn("es:PROFILE_1:EMPTY_FIELD:" + missing, issues)

    def test_anonymous_es_literal_whitespace_password_matches_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = synthetic_root(tmp)
            p = root / "czjLLM/config_es/private/anon.py"
            with patch.dict(os.environ, {"CZJLLM_ENV": "development"}):
                for user, password, expect_allowed in (
                    ("", " ", False),
                    ("", "\t", False),
                    (" ", "", True),
                    (None, None, True),
                    ("", None, True),
                    ("", "", True),
                ):
                    with self.subTest(user=repr(user), expected=expect_allowed):
                        # Synthetic values stay in a temporary ignored profile.
                        p.write_text(
                            "es_host='http://localhost:9200'\n"
                            "es_index='synthetic'\n"
                            "es_user=" + repr(user) + "\n"
                            "es_pass=" + repr(password) + "\n",
                            encoding="utf-8",
                        )
                        summary, errors = inspect(
                            root, kind="es", profile="anon.py",
                            allow_anonymous_es=True,
                        )
                        config = {
                            "es_host": "http://localhost:9200",
                            "es_index": "synthetic", "es_user": user,
                            "es_pass": password,
                        }
                        if expect_allowed:
                            self.assertEqual(errors, [])
                            self.assertEqual(summary["es"]["checked"], 1)
                            self.assertIs(validate_es_config(config), config)
                        else:
                            self.assertIn("es:PROFILE_1:EMPTY_FIELD:es_pass", errors)
                            with self.assertRaisesRegex(ValueError, "incomplete"):
                                validate_es_config(config)

    def test_dynamic_empty_password_is_not_claimed_anonymous(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = synthetic_root(tmp)
            p = root / "czjLLM/config_es/private/dynamic.py"
            p.write_text(
                "es_host='http://localhost:9200'\n"
                "es_index='synthetic'\n"
                "es_user=''\n"
                "es_pass=''.join(())\n", encoding="utf-8",
            )
            with patch.dict(os.environ, {"CZJLLM_ENV": "dev"}):
                summary, issues = inspect(
                    root, kind="es", profile="dynamic.py",
                    allow_anonymous_es=True,
                )
            self.assertEqual(summary["es"]["checked"], 0)
            self.assertIn("es:PROFILE_1:EMPTY_FIELD:es_user", issues)

    def test_explicit_anonymous_es_rejected_in_production_and_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = synthetic_root(tmp)
            p = root / "czjLLM/config_es/private/anon.py"
            p.write_text('''es_host = "http://localhost:9200"
es_user = ""
es_pass = ""
es_index = "synthetic"
''', encoding="utf-8")
            for environment in ("production", "prod", "staging", "unknown"):
                with self.subTest(environment=environment):
                    with patch.dict(os.environ, {"CZJLLM_ENV": environment}):
                        report, issues = inspect(
                            root, kind="es", profile="anon.py",
                            allow_anonymous_es=True,
                        )
                        self.assertEqual(report, {})
                        self.assertEqual(
                            issues, ["ANONYMOUS_NOT_ALLOWED_IN_ENVIRONMENT"]
                        )

    def test_anonymous_exception_never_waives_es_host_or_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = synthetic_root(tmp)
            p = root / "czjLLM/config_es/private/anon.py"
            with patch.dict(os.environ, {"CZJLLM_ENV": "local"}):
                p.write_text('''es_host = ""
es_user = ""
es_pass = ""
es_index = ""
''', encoding="utf-8")
                _, issues = inspect(
                    root, kind="es", profile="anon.py", allow_anonymous_es=True
                )
                self.assertIn("es:PROFILE_1:EMPTY_FIELD:es_host", issues)
                self.assertIn("es:PROFILE_1:EMPTY_FIELD:es_index", issues)

    def test_anonymous_exception_requires_single_es_python_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = synthetic_root(tmp)
            with patch.dict(os.environ, {"CZJLLM_ENV": "dev"}):
                for kind, profile in (
                    ("both", None), ("es", None),
                    ("sql", "example.py"), ("es", "example.yaml"),
                ):
                    with self.subTest(kind=kind, profile=profile):
                        report, issues = inspect(
                            root, kind=kind, profile=profile,
                            allow_anonymous_es=True,
                        )
                        self.assertEqual(report, {})
                        self.assertEqual(issues, ["INVALID_ANONYMOUS_SELECTION"])

    def test_anonymous_es_runtime_contract_is_dev_only(self):
        # Direct helper validation, no DB/ES connection or configuration execution.
        config = {"es_host": "http://localhost:9200", "es_user": "",
                  "es_pass": "", "es_index": "synthetic"}
        with patch.dict(os.environ, {"CZJLLM_ENV": "development"}):
            self.assertIs(validate_es_config(config), config)
        with patch.dict(os.environ, {"CZJLLM_ENV": "production"}):
            with self.assertRaisesRegex(ValueError, "ES production connection"):
                validate_es_config(config)

    def test_anonymous_cli_explicit_notice_and_no_secret_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = synthetic_root(tmp)
            p = root / "czjLLM/config_es/private/anon.py"
            p.write_text('''es_host = "http://localhost:9200"
es_user = ""
es_pass = ""
es_index = "synthetic"
''', encoding="utf-8")
            stdout = io.StringIO()
            with patch.dict(os.environ, {"CZJLLM_ENV": "development"}):
                with patch.object(sys, "argv", [
                    "preflight", "--root", str(root), "--kind", "es",
                    "--profile", "anon.py", "--allow-anonymous-es",
                ]):
                    with contextlib.redirect_stdout(stdout):
                        result = main()
            self.assertEqual(result, 0)
            self.assertIn("Development-only anonymous ES opt-in", stdout.getvalue())
            self.assertIn("No connection made", stdout.getvalue())
            self.assertNotIn(str(root), stdout.getvalue())

    def test_no_private_credentials_in_log_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = synthetic_root(tmp)
            p = root / "czjLLM/config_sql/private/example.py"
            marker = "".join(("test", "-", "not", "-", "secret"))
            p.write_text(
                "server='example.invalid'\nusername='operator'\n"
                "password=" + repr(marker) +
                "\ndatabase_name='test'\ntable_name='test'\n",
                encoding="utf-8",
            )
            summary, errors = inspect(root, kind="sql", profile="example.py")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                for issue in errors:
                    print(issue)
                print(summary)
            self.assertNotIn(marker, output.getvalue())


if __name__ == "__main__":
    unittest.main()
