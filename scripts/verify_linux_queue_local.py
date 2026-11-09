#!/usr/bin/env python3
"""Offline, disposable Linux local-filesystem Queue fixture acceptance.

Never accepts a live Queue, SQL/ES destination or provider endpoint path.
Results are fixed-code-only and cannot authorize replay or production writes.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parents[1]
SUITES = (
    ("linux_local_fixture", "tests/prompt_pipeline/test_queue_linux_local_fixture.py"),
)
LIMITATIONS = [
    "DISPOSABLE_FIXTURES_ONLY",
    "LIVE_QUEUE_UNVERIFIED",
    "LOCAL_CRASH_RESTART_UNVERIFIED",
    "SMB_DEFERRED_UNVERIFIED",
    "SQL_ES_SINK_ACK_AND_READBACK_UNVERIFIED",
    "NO_REPLAY_AUTHORIZATION",
]
ALLOWED_ENV = {"PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE"}
_SHA = re.compile(r"[a-f0-9]{40}\Z")


def evaluate(platform: str, version: tuple[int, int], pytest_available: bool,
             run_suite) -> dict:
    """A green disposable test is fixture evidence, never deployment proof."""
    checks = {
        "linux_host": "PASS" if platform == "linux" else "BLOCKED",
        "supported_python": "PASS" if version in ((3, 10), (3, 11)) else "BLOCKED",
        "pytest_installed": "PASS" if pytest_available else "BLOCKED",
    }
    checks.update({name: "NOT_RUN" for name, _ in SUITES})
    diagnostics = {}
    if all(checks[name] == "PASS" for name in
           ("linux_host", "supported_python", "pytest_installed")):
        for name, relative in SUITES:
            passed, detail = run_suite(relative)
            checks[name] = "PASS" if passed else "FAIL"
            diagnostics[name] = detail
    return {
        "report_version": 1,
        "probe": "LINUX_LOCAL_QUEUE_OPERATOR_FIXTURE",
        "fixture_status": (
            "PASS" if all(value == "PASS" for value in checks.values())
            else "REVIEW_REQUIRED"
        ),
        "deployment_status": "NOT_VERIFIED",
        "checks": checks,
        "suite_diagnostics": diagnostics,
        "limitations": list(LIMITATIONS),
    }


def _run_suite(relative: str) -> tuple[bool, dict]:
    """Only checked-in fixtures; suppress raw subprocess/JUnit error details."""
    if relative not in {path for _, path in SUITES}:
        return False, {"code": "SUITE_NOT_ALLOWLISTED"}
    env = {key: value for key, value in os.environ.items()
           if key.upper() in ALLOWED_ENV}
    env.update({
        "PYTHONPATH": str(REPO_ROOT),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    })
    # The operator's TMPDIR may point to live data. Always use /tmp fixtures.
    try:
        tmp_root = Path("/tmp")
        root_info = tmp_root.lstat()
        if (not stat.S_ISDIR(root_info.st_mode) or
                not (root_info.st_mode & stat.S_ISVTX)):
            return False, {"code": "SAFE_TMP_UNAVAILABLE"}
        with tempfile.TemporaryDirectory(
            prefix="queue-local-fixture-", dir=tmp_root,
        ) as directory:
            xml = Path(directory) / "junit.xml"
            args = [
                sys.executable, "-m", "pytest", "-q", relative,
                "--maxfail=1", "--disable-warnings",
                "-p", "no:cacheprovider",
                "--noconftest",  # Never import project conftest / local dotenv.
                "--basetemp", str(Path(directory) / "pytest"),
                "--junitxml", str(xml),
            ]
            try:
                result = subprocess.run(
                    args, cwd=REPO_ROOT, env=env, shell=False,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, check=False, timeout=180,
                )
            except (OSError, subprocess.TimeoutExpired):
                return False, {"code": "RUNNER_UNAVAILABLE_OR_TIMEOUT"}
            if not xml.is_file():
                return False, {"code": "JUNIT_MISSING"}
            try:
                root = ET.parse(xml).getroot()
                cases = list(root.iter("testcase"))
            except (OSError, ET.ParseError):
                return False, {"code": "JUNIT_INVALID"}
            failed = [
                i + 1 for i, case in enumerate(cases)
                if case.find("failure") is not None
                or case.find("error") is not None
            ]
            skipped = sum(
                case.find("skipped") is not None for case in cases
            )
            accepted = (
                result.returncode == 0 and len(cases) > 0
                and not failed and not skipped
            )
            return accepted, {
                "code": (
                    "PASS" if accepted else
                    "NO_EXECUTED_TESTS" if not cases or skipped == len(cases) else
                    "UNEXPECTED_TEST_SKIP" if skipped else
                    "PYTEST_NONZERO" if result.returncode else
                    "TEST_CASE_FAILED"
                ),
                "total_cases": len(cases),
                "skipped_cases": skipped,
                "failure_ordinals": failed[:20],
                "runner_code": "OK" if result.returncode == 0 else "PYTEST_NONZERO",
            }
    except OSError:
        return False, {"code": "SAFE_TMP_UNAVAILABLE"}


def _git_identity() -> tuple[str, str]:
    """Report source identity, refusing tracked or untracked checkout changes.

    Untracked executable additions could change imports or fixture behavior.
    Treat any nonignored untracked file as DIRTY, not a trusted commit.
    Never copy status file paths into reports.
    """
    env = {key: value for key, value in os.environ.items()
           if key.upper() in ALLOWED_ENV}
    try:
        rev = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, check=False, timeout=5,
        )
        clean = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=REPO_ROOT, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            check=False, timeout=5,
        )
        sha = rev.stdout.decode("ascii", errors="ignore").strip()
        if rev.returncode or not _SHA.fullmatch(sha):
            return "UNKNOWN", "NOT_VERIFIED"
        if clean.returncode:
            return sha, "NOT_VERIFIED"
        return sha, "CLEAN" if not clean.stdout else "DIRTY"
    except (OSError, subprocess.TimeoutExpired):
        return "UNKNOWN", "NOT_VERIFIED"


def _write_report(report: dict, directory: Path) -> None:
    """Create a private, unique JSON report through a nofollow directory fd."""
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        pass
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    dir_fd = os.open(directory, flags)
    try:
        info = os.fstat(dir_fd)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077):
            raise ValueError("OUTPUT_DIRECTORY_UNSAFE")
        name = "queue_linux_fixture_" + uuid.uuid4().hex + ".json"
        out_fd = os.open(
            name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600, dir_fd=dir_fd,
        )
        with os.fdopen(out_fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, sort_keys=True, ensure_ascii=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(dir_fd)


def main() -> int:
    available = importlib.util.find_spec("pytest") is not None
    report = evaluate(
        "linux" if sys.platform.startswith("linux") else "other",
        sys.version_info[:2], available, _run_suite,
    )
    revision, checkout = _git_identity()
    report["source_commit"] = revision
    report["checkout_status"] = checkout
    if checkout != "CLEAN":
        report["fixture_status"] = "REVIEW_REQUIRED"
    try:
        _write_report(report, Path.home() / "queue-linux-acceptance-results")
    except (OSError, ValueError):
        print("REVIEW_REQUIRED: REPORT_WRITE_UNAVAILABLE")
        return 2
    if report["fixture_status"] == "PASS":
        print("FIXTURE_PASS_ONLY: live Queue, restart and SQL/ES remain NOT_VERIFIED")
        return 0
    print("REVIEW_REQUIRED: disposable Linux fixture or revision not accepted")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
