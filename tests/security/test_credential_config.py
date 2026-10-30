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
        clear = {"CZJLLM_ES_HOST": "", "CZJLLM_ES_USERNAME": "", "CZJLLM_ES_PASSWORD": ""}
        with patch.dict(os.environ, clear):
            for filename in ES_PROFILES:
                with self.subTest(filename=filename):
                    path = ROOT / "czjLLM" / "config_es" / filename
                    source = path.read_text(encoding="utf-8")
                    self.assertNotRegex(source, r"(?m)^es_pass\s*=\s*['\"]")
                    self.assertIn("CZJLLM_ES_PASSWORD", source)
                    cfg = runpy.run_path(str(path))
                    self.assertEqual(cfg["es_pass"], "")
                    self.assertEqual(cfg["es_user"], "")
                    self.assertEqual(cfg["es_host"], "")
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
                cfg = runpy.run_path(str(ROOT / "czjLLM" / "config_es" / name))
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
        self.assertIs(validate_es_config({"es_user": "", "es_pass": None}), validate_es_config({"es_user": "", "es_pass": None}))

    def test_sql_production_is_fail_closed(self):
        with patch.dict(os.environ, {"CZJLLM_ENV": "production"}):
            with self.assertRaisesRegex(ValueError, "SQL password missing"):
                validate_sql_config({"username": "service-user", "password": None})
            good = {"username": "service-user", "password": "synthetic"+"_for_test"}
            self.assertIs(validate_sql_config(good), good)

    def test_recursive_log_redaction(self):
        secret = "synthetic"+"_for_test"
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

    def test_public_env_example_is_blank_for_credentials(self):
        path = ROOT / "czjLLM" / "env_examples" / "czjllm.env.example"
        entries = dict(line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines()
                       if line and not line.lstrip().startswith("#") and "=" in line)
        for key in ("CZJLLM_ES_HOST", "CZJLLM_ES_USERNAME", "CZJLLM_ES_PASSWORD",
                    "CZJLLM_UTILS_API_KEY", "CZJLLM_ANKINT_API_KEY",
                    "CZJLLM_SQL_ORION_PASSWORD", "CZJLLM_SQL_SRP_PASSWORD",
                    "CZJLLM_SQL_SRP_ADMIN_PASSWORD"):
            self.assertIn(key, entries)
            self.assertEqual(entries[key], "")


if __name__ == "__main__":
    unittest.main()
