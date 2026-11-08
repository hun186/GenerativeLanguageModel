"""Cross-platform fail-closed checks for operator-only NTFS fixture launcher."""
import json
import os
from pathlib import Path
import subprocess
import sys

from scripts import verify_windows_queue_ntfs_local as probe


def test_invalid_host_version_or_dependency_refuses_without_running_suites():
    def forbidden(_path):
        raise AssertionError("must not run")
    for platform, version, available in [
        ("posix", (3, 11), True),
        ("nt", (3, 12), True),
        ("nt", (3, 10), False),
    ]:
        report = probe.evaluate(platform, version, available, forbidden)
        assert report["fixture_status"] == "REVIEW_REQUIRED"
        assert report["deployment_status"] == "NOT_VERIFIED"
        assert all(report["checks"][name] == "NOT_RUN"
                   for name, _ in probe.SUITES)


def test_exact_three_suites_pass_but_never_prove_deployment():
    ran = []
    report = probe.evaluate("nt", (3, 11), True, lambda path: ran.append(path) or True)
    assert ran == [path for _name, path in probe.SUITES]
    assert report["fixture_status"] == "PASS"
    assert report["deployment_status"] == "NOT_VERIFIED"
    assert "NO_REPLAY_AUTHORIZATION" in report["limitations"]


def test_one_failed_suite_is_review_required():
    report = probe.evaluate(
        "nt", (3, 10), True,
        lambda path: not path.endswith("test_queue_win32_ntfs_acceptance.py"),
    )
    assert report["fixture_status"] == "REVIEW_REQUIRED"
    assert report["checks"]["ntfs_real_fixture"] == "FAIL"


def test_runner_uses_disposable_tmp_and_sanitized_environment(monkeypatch):
    monkeypatch.setenv("API_SECRET_NEVER_EXPORT", "SENSITIVE_DO_NOT_PRINT")
    monkeypatch.setenv("PYTEST_ADDOPTS", "--bad-option")
    monkeypatch.setenv("PYTEST_PLUGINS", "private.plugin")
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    monkeypatch.setenv("PYTHONUSERBASE", r"C:\fake-user-python-site")
    seen = []

    def fake_run(args, **kwargs):
        seen.append((args, kwargs))
        junit = Path(args[args.index("--junitxml") + 1])
        junit.write_text('<testsuite><testcase name="test_ok"/></testsuite>',
                         encoding="utf-8")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    assert probe._run_suite(probe.SUITES[0][1])[0]
    args, kwargs = seen[0]
    assert args[:3] == [sys.executable, "-m", "pytest"]
    assert args[4] == probe.SUITES[0][1]
    assert "--basetemp" in args and "--maxfail=1" in args
    assert kwargs["shell"] is False
    assert kwargs["stdin"] == kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL
    assert "API_SECRET_NEVER_EXPORT" not in kwargs["env"]
    assert "PYTEST_ADDOPTS" not in kwargs["env"]
    assert "PYTEST_PLUGINS" not in kwargs["env"]
    assert kwargs["env"]["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert "PYTHONNOUSERSITE" not in kwargs["env"]
    assert kwargs["env"]["PYTHONUSERBASE"] == r"C:\fake-user-python-site"
    assert kwargs["env"]["PSModulePath"] == (
        r"C:\Windows\System32\WindowsPowerShell\v1.0\Modules"
    )


def test_green_pytest_exit_with_unexpected_skip_fails_fixture(monkeypatch):
    """A security test skipped for permissions is not a passing acceptance."""
    def fake_run(args, **kwargs):
        junit = Path(args[args.index("--junitxml") + 1])
        junit.write_text(
            '<testsuite><testcase name="passed"/>'
            '<testcase name="native_capability"><skipped message="no privilege"/>'
            '</testcase></testsuite>',
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    passed, detail = probe._run_suite(probe.SUITES[2][1])
    assert not passed
    assert detail["runner_code"] == "OK"
    assert detail["skipped_cases"] == 1
    assert detail["acceptance_code"] == "UNEXPECTED_TEST_SKIP"
    assert "native_capability" not in json.dumps(detail)


def test_all_skipped_cannot_pass_even_if_pytest_exits_zero(monkeypatch):
    def fake_run(args, **kwargs):
        junit = Path(args[args.index("--junitxml") + 1])
        junit.write_text(
            '<testsuite><testcase name="capability">'
            '<skipped message="unsupported"/></testcase></testsuite>',
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    passed, detail = probe._run_suite(probe.SUITES[1][1])
    assert not passed
    assert detail["total_cases"] == detail["skipped_cases"] == 1
    assert detail["acceptance_code"] == "UNEXPECTED_TEST_SKIP"


def test_expected_platform_skip_alone_never_counts_as_executed(monkeypatch):
    """Even an explicitly allowed skip cannot be the entire acceptance suite."""
    def fake_run(args, **kwargs):
        junit = Path(args[args.index("--junitxml") + 1])
        junit.write_text(
            '<testsuite><testcase '
            'name="test_non_windows_probe_fails_closed_without_attempted_path_open">'
            '<skipped message="native Windows acceptance tested separately"/>'
            '</testcase></testsuite>',
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    monkeypatch.setattr(probe, "_count_unexpected_skips", lambda *_: 0)
    passed, detail = probe._run_suite(probe.SUITES[0][1])
    assert not passed
    assert detail["acceptance_code"] == "NO_EXECUTED_TESTS"
    assert detail["runner_code"] == "OK"


def test_only_exact_non_windows_platform_skip_is_allowed():
    from xml.etree import ElementTree as ET

    xml = ET.fromstring(
        '<testsuite><testcase '
        'name="test_non_windows_probe_fails_closed_without_attempted_path_open">'
        '<skipped message="native Windows acceptance tested separately"/>'
        '</testcase></testsuite>'
    )
    cases = list(xml.iter("testcase"))
    handles = probe.SUITES[0][1]
    assert probe._count_unexpected_skips(cases, handles, "nt") == 0
    assert probe._count_unexpected_skips(cases, handles, "posix") == 1
    assert probe._count_unexpected_skips(cases, probe.SUITES[1][1], "nt") == 1
    cases[0].find("skipped").set("message", "unexpected failure")
    assert probe._count_unexpected_skips(cases, handles, "nt") == 1


def test_runner_timeout_fails_closed(monkeypatch):
    def timeout(args, **kwargs):
        raise subprocess.TimeoutExpired(args, 180)
    monkeypatch.setattr(probe.subprocess, "run", timeout)
    assert probe._run_suite(probe.SUITES[0][1])[0] is False


def test_unique_reports_are_path_free_and_no_overwrite(tmp_path):
    report = probe.evaluate("nt", (3, 10), True, lambda _p: True)
    first = probe._write_report(tmp_path, report)
    second = probe._write_report(tmp_path, report)
    assert first != second
    for filename in (first, second):
        content = (tmp_path / filename).read_text(encoding="utf-8")
        assert json.loads(content) == report
        assert str(tmp_path) not in content


def test_output_symlink_refused(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        return
    report = probe.evaluate("posix", (3, 11), True, lambda _p: True)
    try:
        probe._write_report(alias, report)
    except OSError:
        pass
    else:
        raise AssertionError("output symlink was accepted")
    assert not list(target.iterdir())


def test_real_cli_non_windows_has_fixed_codes_and_no_source_path(tmp_path):
    if os.name == "nt":
        return
    result = subprocess.run(
        [sys.executable, str(Path(probe.__file__).resolve()),
         "--output-dir", str(tmp_path / "reports")],
        cwd=tmp_path, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 2
    assert str(tmp_path) not in result.stdout
    data = json.loads(result.stdout)
    assert data["checks"]["windows_host"] == "BLOCKED"
    assert data["deployment_status"] == "NOT_VERIFIED"
    assert (tmp_path / "reports" / data["report_file"]).is_file()


def test_junit_failure_is_only_numeric_ordinals(monkeypatch):
    def fake_run(args, **kwargs):
        junit = Path(args[args.index("--junitxml") + 1])
        junit.write_text(
            '<testsuite><testcase name="test_ok"/>'
            '<testcase name="SENSITIVE_FILENAME"><failure>SECRET</failure></testcase>'
            '<testcase name="test_skip"><skipped/></testcase></testsuite>',
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args, 1)

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    passed, detail = probe._run_suite(probe.SUITES[2][1])
    assert not passed
    assert detail == {
        "total_cases": 3, "skipped_cases": 1,
        "failure_ordinals": [2], "failure_codes": ["TEST_CASE_FAILED"],
        "runner_code": "PYTEST_NONZERO",
        "acceptance_code": "UNEXPECTED_TEST_SKIP",
    }
    assert "SENSITIVE" not in json.dumps(detail)
    assert "SECRET" not in json.dumps(detail)


def test_explicit_junction_failure_marker_is_categorized_without_raw_text(monkeypatch):
    def fake_run(args, **kwargs):
        path = Path(args[args.index("--junitxml") + 1])
        path.write_text(
            '<testsuite><testcase name="private">'
            '<failure message="WINDOWS_JUNCTION_SETUP_FAILED">'
            'C:/private/secret</failure></testcase></testsuite>',
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args, 1)

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    ok, detail = probe._run_suite(probe.SUITES[2][1])
    assert not ok
    assert detail["failure_codes"] == ["JUNCTION_SETUP_FAILED"]
    assert "private" not in json.dumps(detail)
    assert "secret" not in json.dumps(detail)

def test_known_junction_scan_marker_redacted(monkeypatch):
    def fake_run(args, **kwargs):
        xml = Path(args[args.index("--junitxml") + 1])
        xml.write_text(
            '<testsuite><testcase name="secret-path">'
            '<failure message="AssertionError: WINDOWS_JUNCTION_SCAN_INCOMPLETE">'
            'D:/private/secret</failure></testcase></testsuite>',
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args, 1)

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    passed, detail = probe._run_suite(probe.SUITES[2][1])
    assert not passed
    assert detail["failure_codes"] == ["JUNCTION_SCAN_INCOMPLETE"]
    assert "private" not in json.dumps(detail)
    assert "secret-path" not in json.dumps(detail)

def test_unknown_junit_failure_type_is_not_exposed(monkeypatch):
    def fake_run(args, **kwargs):
        xml = Path(args[args.index("--junitxml") + 1])
        xml.write_text(
            '<testsuite><testcase name="secret">'
            '<failure type="FileNotFoundError" message="PRIVATE_PATH">'
            'C:/sensitive/filename</failure></testcase></testsuite>',
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args, 1)

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    passed, detail = probe._run_suite(probe.SUITES[2][1])
    assert not passed
    assert detail["failure_codes"] == ["FILE_NOT_FOUND_EXCEPTION"]
    assert "PRIVATE_PATH" not in json.dumps(detail)
    assert "filename" not in json.dumps(detail)

def test_native_junction_fixed_error_marker_is_redacted(monkeypatch):
    def fake_run(args, **kwargs):
        path = Path(args[args.index("--junitxml") + 1])
        path.write_text(
            '<testsuite><testcase name="C:/private">'
            '<failure message="WINDOWS_JUNCTION_NATIVE_SET_FAILED">'
            'secret runtime path</failure></testcase></testsuite>',
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args, 1)

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    passed, detail = probe._run_suite(probe.SUITES[2][1])
    assert not passed
    assert detail["failure_codes"] == ["JUNCTION_NATIVE_SET_FAILED"]
    assert "private" not in json.dumps(detail)
    assert "secret" not in json.dumps(detail)
