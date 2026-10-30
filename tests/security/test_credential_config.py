"""Synthetic/no-network regressions for private production credentials."""
from __future__ import annotations

import os
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

from czjLLM.utilities.credential_config import (
    REDACTED, redact_config, validate_es_config, validate_sql_config,
)

ROOT = Path(__file__).resolve().parents[2]
ES_PROFILES = [
    "akconfig_es_fishing.py",
    "akconfig_es_test.py",
    "akconfig_es_test_133.py",
    "akconfig_es_test_mil.py",
    "akconfig_es_test_nav_intel_sentences_133.py",
    "akconfig_es_test_satmeta_133.py",
    "akconfig_es_test_srp_133.py",
]


class CredentialConfigTests(unittest.TestCase):
    def test_es_profiles_never_embed_auth_or_production_endpoints(self):
        clear = {"CZJLLM_ENV": "dev", "CZJLLM_ES_HOST": "", "CZJLLM_ES_USERNAME": "", "CZJLLM_ES_PASSWORD": ""}
        with patch.dict(os.environ, clear):
            for filename in ES_PROFILES:
                with self.subTest(filename=filename):
                    path = ROOT / "czjLLM" / "config_es" / (filename + ".example")
                    source = path.read_text(encoding="utf-8")
                    self.assertNotRegex(source, r"(?m)^es_pass\s*=\s*['\"]")
                    self.assertIn("CZJLLM_ES_PASSWORD", source)
                    cfg = runpy.run_path(str(path))
                    self.assertEqual(cfg["es_pass"], "")
                    self.assertEqual(cfg["es_user"], "")
                    self.assertEqual(cfg["es_host"], "http://localhost:9200")
        # A set of missing variables must not reuse old hardcoded connection values.
        for variable in clear:
            with patch.dict(os.environ, {variable: ""}, clear=False):
                pass

    def test_env_profile_imports_private_values_without_source_fallback(self):
        fake = {"CZJLLM_ES_HOST": "https://example.invalid:9200",
                "CZJLLM_ES_USERNAME": "service-user",
                "CZJLLM_ES_PASSWORD": "synthetic"+"_for_test"}
        with patch.dict(os.environ, fake):
            for name in ES_PROFILES:
                cfg = runpy.run_path(str(ROOT / "czjLLM" / "config_es" / (name + ".example")))
                self.assertEqual(cfg["es_host"], fake["CZJLLM_ES_HOST"])
                self.assertEqual(cfg["es_user"], fake["CZJLLM_ES_USERNAME"])
                self.assertEqual(cfg["es_pass"], fake["CZJLLM_ES_PASSWORD"])
                self.assertIs(validate_es_config(cfg), cfg)

    def test_partial_es_auth_fails_without_disclosing_input(self):
        for bad in ({"es_user": "user", "es_pass": None},
                    {"es_user": "", "es_pass": "synthetic"+"_for_test"}):
            with self.assertRaises(ValueError) as caught:
                validate_es_config(bad)
            self.assertNotIn("synthetic_for_test", str(caught.exception))
        anonymous = {"es_user": "", "es_pass": None}
        self.assertIs(validate_es_config(anonymous), anonymous)

    def test_es_production_missing_credentials_is_fail_closed(self):
        with patch.dict(os.environ, {"CZJLLM_ENV": "production"}):
            with self.assertRaisesRegex(ValueError, "ES production connection requires"):
                validate_es_config({"es_host": "https://example.invalid:9200",
                                    "es_user": "", "es_pass": None})
            private = {"es_host": "https://example.invalid:9200",
                       "es_user": "service-user", "es_pass": "synthetic"+"_for_test"}
            self.assertIs(validate_es_config(private), private)

    def test_supported_es_hosts_list_is_accepted_in_production(self):
        fake_auth = "".join(["synthetic", "_for_test"])
        with patch.dict(os.environ, {"CZJLLM_ENV": "production"}):
            for hosts in (["https://node-a.example.invalid:9200"],
                          ["https://node-a.example.invalid:9200",
                           "https://node-b.example.invalid:9200"],
                          [{"host": "node-a.example.invalid", "port": 9200}]):
                with self.subTest(hosts_type=type(hosts[0]).__name__):
                    cfg = {"hosts": hosts, "es_user": "service-user",
                           "es_pass": fake_auth, "es_host": ""}
                    self.assertIs(validate_es_config(cfg), cfg)
            bad = {"hosts": [" "], "es_user": "service-user",
                   "es_pass": fake_auth, "es_host": ""}
            with self.assertRaisesRegex(ValueError, "ES production connection requires"):
                validate_es_config(bad)

    def test_real_es_profiles_refuse_missing_host_in_production(self):
        # This test executes safe public example bodies; no connection is opened.
        fake = {"CZJLLM_ENV": "production",
                "CZJLLM_ES_USERNAME": "service-user",
                "CZJLLM_ES_PASSWORD": "".join(["synthetic", "_for_test"])}
        with patch.dict(os.environ, fake):
            os.environ.pop("CZJLLM_ES_HOST", None)
            for filename in ES_PROFILES:
                with self.subTest(filename=filename):
                    cfg = runpy.run_path(str(ROOT / "czjLLM" / "config_es" / (filename + ".example")))
                    self.assertEqual(cfg["es_host"], "")
                    with self.assertRaisesRegex(ValueError, "ES production connection requires"):
                        validate_es_config(cfg)

    def test_sql_production_is_fail_closed(self):
        with patch.dict(os.environ, {"CZJLLM_ENV": "production"}):
            with self.assertRaisesRegex(ValueError, "SQL production connection requires"):
                validate_sql_config({"username": "service-user", "password": None})
            good = {"server": "example.invalid", "username": "service-user",
                    "password": "synthetic"+"_for_test"}
            self.assertIs(validate_sql_config(good), good)

    def test_sql_profiles_read_per_service_connection_fields(self):
        fake = {
            "CZJLLM_SQL_ORION_SERVER": "orion.example.invalid",
            "CZJLLM_SQL_ORION_USERNAME": "user-orion",
            "CZJLLM_SQL_ORION_PASSWORD": "synthetic"+"_orion",
            "CZJLLM_SQL_SRP_SERVER": "srp.example.invalid",
            "CZJLLM_SQL_SRP_USERNAME": "user-srp",
            "CZJLLM_SQL_SRP_PASSWORD": "synthetic"+"_srp",
            "CZJLLM_SQL_SRP_ADMIN_USERNAME": "user-srp-admin",
            "CZJLLM_SQL_SRP_ADMIN_PASSWORD": "synthetic"+"_admin",
        }
        profiles = (
            ("akconfig_test.py", "ORION", "ORION"),
            ("akconfig_test_to_excel.py", "ORION", "ORION"),
            ("akconfig_test_SRP.py", "SRP", "SRP"),
            ("akconfig_test_SRP - 複製.py", "SRP", "SRP_ADMIN"),
        )
        with patch.dict(os.environ, fake):
            for filename, service, identity in profiles:
                with self.subTest(filename=filename):
                    path = ROOT / "czjLLM" / "config_sql" / (filename + ".example")
                    source = path.read_text(encoding="utf-8")
                    self.assertIn("CZJLLM_SQL_", source)
                    self.assertNotRegex(source, r"(?m)^password\s*=\s*['\"]")
                    cfg = runpy.run_path(str(path))
                    self.assertEqual(cfg["server"], fake[f"CZJLLM_SQL_{service}_SERVER"])
                    self.assertEqual(cfg["username"], fake[f"CZJLLM_SQL_{identity}_USERNAME"])
                    password_identity = identity if identity.endswith("ADMIN") else service
                    self.assertEqual(cfg["password"], fake[f"CZJLLM_SQL_{password_identity}_PASSWORD"])

    def test_real_sql_profiles_refuse_missing_host_in_production(self):
        fake = {
            "CZJLLM_ENV": "production",
            "CZJLLM_SQL_ORION_USERNAME": "orion-user",
            "CZJLLM_SQL_ORION_PASSWORD": "".join(["synthetic", "_orion"]),
            "CZJLLM_SQL_SRP_USERNAME": "srp-user",
            "CZJLLM_SQL_SRP_PASSWORD": "".join(["synthetic", "_srp"]),
            "CZJLLM_SQL_SRP_ADMIN_USERNAME": "admin-user",
            "CZJLLM_SQL_SRP_ADMIN_PASSWORD": "".join(["synthetic", "_admin"]),
        }
        profiles = ("akconfig_test.py", "akconfig_test_to_excel.py",
                    "akconfig_test_SRP.py", "akconfig_test_SRP - 複製.py")
        with patch.dict(os.environ, fake):
            os.environ.pop("CZJLLM_SQL_ORION_SERVER", None)
            os.environ.pop("CZJLLM_SQL_SRP_SERVER", None)
            for filename in profiles:
                with self.subTest(filename=filename):
                    cfg = runpy.run_path(str(ROOT / "czjLLM" / "config_sql" / (filename + ".example")))
                    self.assertEqual(cfg["server"], "")
                    with self.assertRaisesRegex(ValueError, "SQL production connection requires"):
                        validate_sql_config(cfg)

    def test_recursive_log_redaction(self):
        secret = "".join(["synthetic", "_for_test"])
        config = {"password": secret, "es_pass": secret,
                  "http_auth": ("service-user", secret),
                  "nested": [{"api_key": secret, "access_token": secret}],
                  "reset_confirm_code": secret,
                  "server": "example.invalid", "es_host": "https://example.invalid:9200"}
        output = redact_config(config)
        self.assertNotIn(secret, repr(output))
        self.assertEqual(output["password"], REDACTED)
        self.assertEqual(output["http_auth"], REDACTED)
        self.assertEqual(output["nested"][0]["api_key"], REDACTED)
        self.assertEqual(output["server"], config["server"])

    def test_sql_and_es_config_preview_never_logs_raw_credentials(self):
        ui = (ROOT / "czjLLM/config_ui/interactive_config_loader.py").read_text(encoding="utf-8")
        self.assertIn("pprint.pprint(redact_config(sql_cfg)", ui)
        self.assertIn("pprint.pprint(redact_config(es_cfg)", ui)
        for relative in ("czjLLM/es_mode/entry/steps_es.py",
                         "czjLLM/es_mode/entry/steps_es_noeventids.py"):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("redact_config(es_cfg)", source)
            self.assertNotIn('print("es_cfg in resolve_es_connection", es_cfg)', source)

    def test_live_sql_es_profiles_are_not_tracked_at_root(self):
        import subprocess
        root = ROOT
        sql = ("akconfig_test.py", "akconfig_test_to_excel.py",
               "akconfig_test_SRP.py", "akconfig_test_SRP - 複製.py")
        for kind, names in (("config_sql", sql), ("config_es", tuple(ES_PROFILES))):
            for name in names:
                with self.subTest(kind=kind, profile=name):
                    original = root / "czjLLM" / kind / name
                    example = original.with_name(name + ".example")
                    self.assertTrue(example.is_file())
                    self.assertFalse(original.exists())
                    tracked = subprocess.run(
                        ["git", "ls-files", "--error-unmatch", "--", str(original.relative_to(root))],
                        cwd=root, capture_output=True, check=False,
                    )
                    self.assertNotEqual(tracked.returncode, 0)

    def test_public_env_example_is_blank_for_credentials(self):
        path = ROOT / "czjLLM" / "env_examples" / "czjllm.env.example"
        entries = dict(line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines()
                       if line and not line.lstrip().startswith("#") and "=" in line)
        for key in ("CZJLLM_ES_HOST", "CZJLLM_ES_USERNAME", "CZJLLM_ES_PASSWORD",
                    "CZJLLM_UTILS_API_KEY", "CZJLLM_ANKINT_API_KEY",
                    "CZJLLM_SQL_ORION_PASSWORD", "CZJLLM_SQL_SRP_PASSWORD",
                    "CZJLLM_SQL_SRP_ADMIN_PASSWORD", "CZJLLM_SQL_ORION_SERVER",
                    "CZJLLM_SQL_ORION_USERNAME", "CZJLLM_SQL_SRP_SERVER",
                    "CZJLLM_SQL_SRP_USERNAME", "CZJLLM_SQL_SRP_ADMIN_USERNAME"):
            self.assertIn(key, entries)
            self.assertEqual(entries[key], "")


if __name__ == "__main__":
    unittest.main()
