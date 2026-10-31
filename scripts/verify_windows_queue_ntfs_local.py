#!/usr/bin/env python3
"""Offline fixture-only Windows NTFS acceptance; never touches live queues."""
from __future__ import annotations

import argparse
import importlib.util
import json
import ntpath
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parents[1]
SUITES = (
    ("win32_handles", "tests/prompt_pipeline/test_queue_win32_handle_identity.py"),
    ("win32_enumeration", "tests/prompt_pipeline/test_queue_win32_native_enumeration.py"),
    ("ntfs_real_fixture", "tests/prompt_pipeline/test_queue_win32_ntfs_acceptance.py"),
)
ALLOWED_ENV = {
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE",
    "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA", "APPDATA",
    "PYTHONUSERBASE",
}
LIMITATIONS = [
    "DISPOSABLE_FIXTURES_ONLY",
    "LIVE_QUEUE_UNVERIFIED",
    "SMB_AND_CONCURRENT_WRITERS_UNVERIFIED",
    "SQL_ES_SINK_ACK_UNVERIFIED",
    "NO_REPLAY_AUTHORIZATION",
]


def evaluate(platform: str, version: tuple[int, int], pytest_available: bool,
             run_suite) -> dict:
    """Fixed-code result; a passing fixture suite does not prove deployment."""
    checks = {
        "windows_host": "PASS" if platform == "nt" else "BLOCKED",
        "supported_python": "PASS" if version in ((3, 10), (3, 11)) else "BLOCKED",
        "pytest_installed": "PASS" if pytest_available else "BLOCKED",
    }
    checks.update({name: "NOT_RUN" for name, _path in SUITES})
    diagnostics = {}
    if all(checks[k] == "PASS" for k in (
        "windows_host", "supported_python", "pytest_installed"
    )):
        for name, relative_path in SUITES:
            outcome = run_suite(relative_path)
            if isinstance(outcome, tuple):
                passed, detail = outcome
                diagnostics[name] = detail
            else:
                passed = outcome
            checks[name] = "PASS" if passed else "FAIL"
    fixture_pass = all(value == "PASS" for value in checks.values())
    return {
        "report_version": 1,
        "probe": "WINDOWS_QUEUE_NTFS_OPERATOR_FIXTURE",
        "fixture_status": "PASS" if fixture_pass else "REVIEW_REQUIRED",
        "deployment_status": "NOT_VERIFIED",
        "checks": checks,
        "suite_diagnostics": diagnostics,
        "limitations": LIMITATIONS.copy(),
    }


def _run_suite(relative_path: str) -> tuple[bool, dict]:
    """Run a checked-in suite and parse only numeric JUnit totals/ordinals.

    Never record raw pytest stdout, stderr, tracebacks, filenames or test names.
    Failure ordinals are 1-based positions within the JUnit testcases.
    """
    env = {key: val for key, val in os.environ.items()
           if key.upper() in ALLOWED_ENV}
    # A site-installed pytest may live in the operator's user site.
    # Disable third-party pytest plugin autoload, not the user site itself.
    env.update({
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONPATH": str(REPO_ROOT),
    })
    # The Junction regression invokes Windows PowerShell 5.1 New-Item.
    # A stripped PSModulePath makes its built-in Management cmdlets fail.
    # Pin to system-owned module directory instead of inheriting user modules.
    systemroot = next((v for k, v in env.items()
                       if k.upper() == "SYSTEMROOT"), None)
    if systemroot:
        env["PSModulePath"] = ntpath.join(
            systemroot, "System32", "WindowsPowerShell", "v1.0", "Modules"
        )
    try:
        with tempfile.TemporaryDirectory(prefix="queue-ntfs-fixture-") as base:
            junit = Path(base) / "junit.xml"
            argv = [
                sys.executable, "-m", "pytest", "-q", relative_path,
                "--maxfail=1", "--disable-warnings", "-p", "no:cacheprovider",
                "--basetemp", str(Path(base) / "pytest"),
                "--junitxml", str(junit),
            ]
            proc = subprocess.run(
                argv, cwd=REPO_ROOT, env=env, shell=False,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=180, check=False,
            )
            if not junit.is_file():
                return False, {"code": "JUNIT_MISSING"}
            try:
                root = ET.parse(junit).getroot()
                cases = list(root.iter("testcase"))
                failures = [
                    i + 1 for i, case in enumerate(cases)
                    if case.find("failure") is not None
                    or case.find("error") is not None
                ]
                skipped = sum(case.find("skipped") is not None for case in cases)
                # Classify only explicitly known marker strings from test code;
                # never copy arbitrary pytest/JUnit messages to report fields.
                failure_codes = []
                for case in cases:
                    for tag in ("failure", "error"):
                        for node in case.findall(tag):
                            raw = (node.get("message") or "") + (node.text or "")
                            if "WINDOWS_JUNCTION_SETUP_FAILED" in raw:
                                failure_codes.append("JUNCTION_SETUP_FAILED")
                            elif "WINDOWS_NTFS_VOLUME_REQUIRED" in raw:
                                failure_codes.append("NTFS_VOLUME_REQUIRED")
                            elif "WINDOWS_NATIVE_RACE_TEST_NOT_EXERCISED" in raw:
                                failure_codes.append("RACE_NOT_EXERCISED")
                            else:
                                marker_codes = (
                                    ("WINDOWS_JUNCTION_SCAN_INCOMPLETE", "JUNCTION_SCAN_INCOMPLETE"),
                                    ("WINDOWS_JUNCTION_UNSAFE_COUNT", "JUNCTION_UNSAFE_COUNT"),
                                    ("WINDOWS_JUNCTION_TODO_COUNT", "JUNCTION_TODO_COUNT"),
                                    ("WINDOWS_JUNCTION_CODE_MISSING", "JUNCTION_CODE_MISSING"),
                                    ("WINDOWS_JUNCTION_REPORT_LEAK", "JUNCTION_REPORT_LEAK"),
                                    ("WINDOWS_JUNCTION_TARGET_CHANGED", "JUNCTION_TARGET_CHANGED"),
                                    ("WINDOWS_JUNCTION_CLEANUP_FAILED", "JUNCTION_CLEANUP_FAILED"),
                                    ("WINDOWS_JUNCTION_PREEXISTING", "JUNCTION_PREEXISTING"),
                                    ("WINDOWS_JUNCTION_TARGET_MISSING", "JUNCTION_TARGET_MISSING"),
                                    ("WINDOWS_JUNCTION_SYSTEM_ROOT_MISSING", "JUNCTION_SYSTEM_ROOT_MISSING"),
                                    ("WINDOWS_JUNCTION_SHELL_MISSING", "JUNCTION_SHELL_MISSING"),
                                    ("WINDOWS_JUNCTION_SHELL_LAUNCH_FAILED", "JUNCTION_SHELL_LAUNCH_FAILED"),
                                    ("WINDOWS_JUNCTION_LINK_NOT_DIRECTORY", "JUNCTION_LINK_NOT_DIRECTORY"),
                                )
                                diagnostic = next((
                                    code for needle, code in marker_codes if needle in raw
                                ), None)
                                if diagnostic is None:
                                    kind = (node.get("type") or "").split(".")[-1]
                                    diagnostic = {
                                        "FileNotFoundError": "FILE_NOT_FOUND_EXCEPTION",
                                        "PermissionError": "PERMISSION_EXCEPTION",
                                        "OSError": "OS_ERROR_EXCEPTION",
                                        "TimeoutExpired": "TIMEOUT_EXCEPTION",
                                        "AssertionError": "UNMARKED_ASSERTION",
                                    }.get(kind, "TEST_CASE_FAILED")
                                failure_codes.append(diagnostic)
            except (ET.ParseError, OSError):
                return False, {"code": "JUNIT_INVALID"}
            detail = {
                "total_cases": len(cases),
                "skipped_cases": skipped,
                "failure_ordinals": failures[:20],
                "failure_codes": failure_codes[:20],
                "runner_code": "OK" if proc.returncode == 0
                else "PYTEST_NONZERO",
            }
            return proc.returncode == 0 and len(cases) > 0 and not failures, detail
    except (OSError, subprocess.TimeoutExpired):
        return False, {"code": "RUNNER_UNAVAILABLE_OR_TIMEOUT"}


def _write_report(output_dir: Path, report: dict) -> str:
    """Write unique no-overwrite JSON with no raw path or payload fields."""
    if output_dir.is_symlink():
        raise OSError("unsafe output directory")
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = "queue_ntfs_fixture_" + uuid.uuid4().hex + ".json"
    path = output_dir / filename
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, sort_keys=True, ensure_ascii=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return filename


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline Windows NTFS fixture validation; no live queue"
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    report = evaluate(
        os.name, sys.version_info[:2],
        importlib.util.find_spec("pytest") is not None, _run_suite,
    )
    try:
        filename = _write_report(args.output_dir, report)
    except OSError:
        print(json.dumps({
            "fixture_status": "REVIEW_REQUIRED", "code": "REPORT_WRITE_FAILED",
        }))
        return 2
    print(json.dumps({
        "fixture_status": report["fixture_status"],
        "deployment_status": report["deployment_status"],
        "checks": report["checks"],
        "suite_diagnostics": report["suite_diagnostics"],
        "report_file": filename,
    }, sort_keys=True))
    return 0 if report["fixture_status"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
