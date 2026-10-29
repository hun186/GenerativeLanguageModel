import unittest

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


if __name__ == "__main__":
    unittest.main()
