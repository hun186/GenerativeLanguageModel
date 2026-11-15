"""Offline static ES rerun-policy preflight: no private Python import or ES I/O."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.inspect_es_rerun_policy_offline import inspect, main


def profiles(tmp_path, python_text="rerun = {}\n", yaml_tail="rerun:\n  enable: true\n"):
    private = tmp_path / "private"
    private.mkdir()
    conn = private / "connection.py"
    task = tmp_path / "task.yaml"
    conn.write_text(python_text.replace("\\\n", "\n"), encoding="utf-8")
    task.write_text(
        ("mode: es\nes_config_file: czjLLM/config_es/connection.py\n"
         + yaml_tail.replace("\\\n", "\n")), encoding="utf-8",
    )
    return task, conn


def test_legacy_rerun_force_and_unknown_values_are_not_exposed(tmp_path, capsys):
    marker = "PRIVATE_SOURCE_VALUE_MARKER"
    raw_private = (
        "local_note = " + repr(marker) + "\n"
        + "rerun = {'enable': True, 'force_since': '2025-11-01T00:00:00Z',"
        + " 'pipeline_hash': 'v3.2.1', 'required_output_checks':"
        + " [{'path': 'Event_Timeline.time_iso', 'validator': 'date'}]}\n"
    )
    task, conn = profiles(
        tmp_path, raw_private,
        "rerun:\n  enable: true\n  pipeline_hash: null\n",
    )
    before = conn.read_bytes()
    result = inspect(task, conn)
    assert result["status"] == "STATIC_PREVIEW_REVIEW_REQUIRED"
    assert "INHERITED_PY_RERUN_KEYS" in result["reason_codes"]
    assert "FORCE_SINCE_ACTIVE" in result["reason_codes"]
    assert "TIMELINE_DATE_MINIMUM_PRESENT" in result["reason_codes"]
    assert "PIPELINE_HASH_ACTIVE" not in result["reason_codes"]
    assert result["inherited_known_key_count"] >= 2
    assert result["production_authorization"] == "NOT_GRANTED"
    assert main(["--task-yaml", str(task), "--connection-py", str(conn)]) == 0
    output = capsys.readouterr().out
    assert marker not in output and "2025-11-01" not in output
    assert "connection.py" not in output and "task.yaml" not in output
    assert conn.read_bytes() == before


def test_task_yaml_explicitly_overrides_legacy_force_policy(tmp_path):
    task, conn = profiles(
        tmp_path, "rerun = {'enable': True, 'force_since': 'SECRET_VALUE',"
        " 'pipeline_hash': 'old', 'force_if_missing_meta': True}\n",
        "rerun:\n  enable: true\n  force_since: null\n"
        "  pipeline_hash: null\n  force_if_missing_meta: false\n"
        "  required_output_checks:\n"
        "    - path: multidim_event_json\n"
        "      validator: multidim_event_time\n",
    )
    result = inspect(task, conn)
    assert result["status"] == "STATIC_PREVIEW_REVIEW_REQUIRED"
    assert "EVENT_FIRST_VALIDATOR_CONFIGURED" in result["reason_codes"]
    assert "FORCE_SINCE_ACTIVE" not in result["reason_codes"]
    assert "PIPELINE_HASH_ACTIVE" not in result["reason_codes"]
    assert "MISSING_META_FORCES_RERUN" not in result["reason_codes"]
    assert "INHERITED_PY_RERUN_KEYS" not in result["reason_codes"]
    assert "LEGACY_PY_RERUN_PRESENT" in result["reason_codes"]
    assert result["runtime_policy"] == "NOT_VERIFIED"


@pytest.mark.parametrize("python_text", [
    "rerun = dict(enable=True)\n",
    "rerun = {'enable': True}\nrerun.update({'force_since': 'SENSITIVE'})\n",
    "def f():\n    rerun = {'enable': True}\n",
    "rerun = {}\nrerun = {}\n",
    "from other_config import rerun\n",
    "exec('rerun = {}')\n",
    "rerun = {'enable': True}\nprint(rerun)\n",
])
def test_dynamic_python_cannot_be_previewed(tmp_path, python_text):
    task, conn = profiles(tmp_path, python_text)
    assert inspect(task, conn)["status"] == "UNAVAILABLE"


@pytest.mark.parametrize("bad_yaml", [
    "rerun:\n  enable: true\nrerun:\n  enable: false\n",
    "rerun: [force_since]\n",
    "rerun:\n  enable: true\n  force_since: !marker PRIVATE\n",
    "rerun:\n  enable: [broken\n",
])
def test_bad_yaml_is_unavailable_without_exception_leak(tmp_path, bad_yaml):
    task, conn = profiles(tmp_path, "rerun = {}\n", bad_yaml)
    assert inspect(task, conn)["status"] == "UNAVAILABLE"


def test_unmatched_python_and_symlink_are_unavailable(tmp_path):
    task, conn = profiles(tmp_path)
    other = conn.with_name("other.py")
    other.write_bytes(conn.read_bytes())
    assert inspect(task, other)["status"] == "UNAVAILABLE"
    symlink = conn.with_name("alias.py")
    try:
        symlink.symlink_to(conn)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this Windows host")
    assert inspect(task, symlink)["status"] == "UNAVAILABLE"


def test_missing_rerun_is_review_only_and_does_not_assume_runtime_safety(tmp_path):
    task, conn = profiles(tmp_path, "es_index = 'SENSITIVE_INDEX'\n", "")
    result = inspect(task, conn)
    assert result["status"] == "STATIC_PREVIEW_REVIEW_REQUIRED"
    assert result["reason_codes"] == ["RERUN_NOT_EXPLICITLY_ENABLED"]
    assert result["stored_es_outputs"] == "NOT_READ"
    assert result["runtime_policy"] == "NOT_VERIFIED"


def test_standalone_cli_from_different_directory_never_imports_private_python(tmp_path):
    task, conn = profiles(tmp_path, "raise AssertionError('DO_NOT_RUN')\nrerun = {}\n")
    script = Path(__file__).resolve().parents[2] / "scripts" / "inspect_es_rerun_policy_offline.py"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    process = subprocess.run(
        [sys.executable, str(script), "--task-yaml", str(task),
         "--connection-py", str(conn)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=25,
    )
    assert process.returncode == 0, process.stderr
    report = json.loads(process.stdout)
    assert report["status"] == "STATIC_PREVIEW_REVIEW_REQUIRED"
    assert report["production_authorization"] == "NOT_GRANTED"
    assert "DO_NOT_RUN" not in process.stdout
    assert process.stderr == ""
