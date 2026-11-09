"""Fail-closed, privacy and portability tests for Linux local fixture launcher."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

from scripts import verify_linux_queue_local as probe


def test_unsupported_os_python_or_pytest_never_dispatches(tmp_path):
    def forbidden(_suite):
        raise AssertionError("unsupported host must not dispatch")

    for platform, version, pytest_available in (
        ("win32", (3, 11), True),
        ("linux", (3, 12), True),
        ("linux", (3, 11), False),
    ):
        result = probe.evaluate(
            platform, version, pytest_available, forbidden,
        )
        assert result["fixture_status"] == "REVIEW_REQUIRED"
        assert result["deployment_status"] == "NOT_VERIFIED"
        assert result["checks"]["linux_local_fixture"] == "NOT_RUN"


def test_only_fixed_linux_fixture_is_accepted_and_deployment_stays_unknown():
    observed = []

    def passed(path):
        observed.append(path)
        return True, {"code": "PASS", "total_cases": 6}

    result = probe.evaluate("linux", (3, 10), True, passed)
    assert result["fixture_status"] == "PASS"
    assert result["deployment_status"] == "NOT_VERIFIED"
    assert observed == [probe.SUITES[0][1]]
    assert "NO_REPLAY_AUTHORIZATION" in result["limitations"]
    assert "SQL_ES_SINK_ACK_AND_READBACK_UNVERIFIED" in result["limitations"]


def test_disposable_junit_runner_sanitizes_env_and_never_logs_tests(
    monkeypatch,
):
    monkeypatch.setenv("UNSAFE_PAYLOAD_ENV", "PRIVATE_NEVER_LOG")
    monkeypatch.setenv("PYTEST_ADDOPTS", "--malicious-extra-option")
    monkeypatch.setenv("PYTEST_PLUGINS", "untrusted.plugin")
    captured = []

    def fake_run(args, **kwargs):
        captured.append((args, kwargs))
        junit = Path(args[args.index("--junitxml") + 1])
        junit.write_text(
            '<testsuite><testcase name="private_test_name"/></testsuite>',
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    passed, detail = probe._run_suite(probe.SUITES[0][1])
    assert passed and detail["code"] == "PASS"
    args, options = captured[0]
    assert args[:3] == [sys.executable, "-m", "pytest"]
    assert "--junitxml" in args and "--basetemp" in args
    assert "--noconftest" in args
    # Disabling plugin autoload alone does not disable tests/conftest.py,
    # which can load local credential environment files.
    assert options["shell"] is False
    assert options["stdin"] == subprocess.DEVNULL
    assert options["stdout"] == subprocess.DEVNULL
    assert options["stderr"] == subprocess.DEVNULL
    assert options["env"]["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert "PYTEST_ADDOPTS" not in options["env"]
    assert "PYTEST_PLUGINS" not in options["env"]
    assert "UNSAFE_PAYLOAD_ENV" not in options["env"]
    assert "private_test_name" not in json.dumps(detail)
    assert "PRIVATE_NEVER_LOG" not in json.dumps(detail)


@pytest.mark.parametrize("junit,return_code,expected", [
    ('<testsuite><testcase name="one"><skipped message="privilege"/>'
     '</testcase></testsuite>', 0, "NO_EXECUTED_TESTS"),
    ('<testsuite><testcase name="passed"/>'
     '<testcase name="skipped"><skipped/></testcase></testsuite>',
     0, "UNEXPECTED_TEST_SKIP"),
    ('<testsuite><testcase name="failed"><failure message="PRIVATE"/>'
     '</testcase></testsuite>', 1, "PYTEST_NONZERO"),
    ('<testsuite></testsuite>', 0, "NO_EXECUTED_TESTS"),
], ids=["all-skipped", "some-skipped", "failed", "zero-tests"])
def test_runner_never_reports_fixture_pass_on_missing_execution(
    monkeypatch, junit, return_code, expected,
):
    def fake_run(args, **_kwargs):
        Path(args[args.index("--junitxml") + 1]).write_text(
            junit, encoding="utf-8",
        )
        return subprocess.CompletedProcess(args, return_code)

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    passed, detail = probe._run_suite(probe.SUITES[0][1])
    assert not passed
    assert detail["code"] == expected
    assert "PRIVATE" not in json.dumps(detail)


def test_unknown_suite_refused_without_subprocess():
    assert probe._run_suite("../../private-file.txt") == (
        False, {"code": "SUITE_NOT_ALLOWLISTED"},
    )


def test_private_nooverwrite_report_mode_and_sanitized_contents(tmp_path):
    directory = tmp_path / "reports"
    report = probe.evaluate(
        "linux", (3, 11), True,
        lambda _p: (True, {"code": "PASS"}),
    )
    report["source_commit"] = "a" * 40
    report["checkout_status"] = "CLEAN"
    probe._write_report(report, directory)
    probe._write_report(report, directory)
    outputs = sorted(directory.glob("queue_linux_fixture_*.json"))
    assert len(outputs) == 2
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    for path in outputs:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        body = path.read_text(encoding="utf-8")
        assert json.loads(body) == report
        assert "PRIVATE" not in body
        assert body.endswith("\n")


def test_symlink_or_permissive_report_directory_refused(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "alias"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises((OSError, ValueError)):
        probe._write_report({"probe": "fixture"}, link)
    assert list(real.iterdir()) == []

    real.chmod(0o755)
    with pytest.raises(ValueError, match="OUTPUT_DIRECTORY_UNSAFE"):
        probe._write_report({"probe": "fixture"}, real)
    assert list(real.iterdir()) == []


def test_git_revision_marks_untracked_executable_addition_dirty(monkeypatch):
    sha = "b" * 40
    seen = []

    def fake_git(args, **kwargs):
        seen.append(args)
        assert kwargs["stdout"] == subprocess.PIPE
        assert kwargs["stderr"] == subprocess.DEVNULL
        if args[1] == "rev-parse":
            return subprocess.CompletedProcess(args, 0, stdout=(sha + "\\n").encode())
        assert "--untracked-files=normal" in args
        return subprocess.CompletedProcess(
            args, 0,
            stdout=b"?? tests/prompt_pipeline/conftest.py\\n",
        )

    monkeypatch.setattr(probe.subprocess, "run", fake_git)
    observed, status = probe._git_identity()
    assert observed == sha
    assert status == "DIRTY"
    assert len(seen) == 2


def test_git_revision_clean_only_when_no_tracked_or_untracked_files(monkeypatch):
    sha = "c" * 40

    def fake_git(args, **_kwargs):
        return subprocess.CompletedProcess(
            args, 0,
            stdout=(sha + "\\n").encode()
            if args[1] == "rev-parse" else b"",
        )

    monkeypatch.setattr(probe.subprocess, "run", fake_git)
    assert probe._git_identity() == (sha, "CLEAN")
