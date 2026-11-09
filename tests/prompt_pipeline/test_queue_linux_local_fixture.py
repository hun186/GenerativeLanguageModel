"""Real Linux local-filesystem, disposable-only Queue safety fixtures.

Never point these tests at a live queue: pytest tmp_path is the only root.
No SQL/ES, credentials, network, LLM or external repair is involved.
"""
import json
import os
from pathlib import Path
import stat
import sys

from czjLLM.prompt_pipeline.runtime_support.prompt_queue import (
    requeue_running_no_clobber,
)
from scripts.inspect_queue_recovery_state import inspect_item


def _item(tmp_path: Path) -> Path:
    item = tmp_path / "disposable-item"
    for name in ("TODO", "RUNNING", "Success"):
        (item / name).mkdir(parents=True, exist_ok=True)
    return item


def test_real_linux_file_id_hardlink_and_nofollow(tmp_path: Path):
    assert sys.platform.startswith("linux")
    assert hasattr(os, "O_NOFOLLOW")
    source = tmp_path / "owned.txt"
    second = tmp_path / "linked.txt"
    source.write_bytes(b"disposable source")
    os.link(source, second)
    assert source.stat().st_dev == second.stat().st_dev
    assert source.stat().st_ino == second.stat().st_ino
    assert source.stat().st_nlink >= 2
    handle = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        assert stat.S_ISREG(os.fstat(handle).st_mode)
        assert os.read(handle, 100) == b"disposable source"
    finally:
        os.close(handle)


def test_real_interrupted_requeue_preserves_independent_todo(tmp_path: Path):
    item = _item(tmp_path)
    source = item / "RUNNING" / "work.txt"
    target = item / "TODO" / "work.txt"
    source.write_bytes(b"older running generation")
    target.write_bytes(b"newer pending generation")
    before = (source.stat().st_ino, target.stat().st_ino)
    assert before[0] != before[1]
    assert requeue_running_no_clobber(str(source)) is False
    assert source.read_bytes() == b"older running generation"
    assert target.read_bytes() == b"newer pending generation"
    assert (source.stat().st_ino, target.stat().st_ino) == before


def test_real_uncontended_interrupted_requeue_keeps_exact_payload(tmp_path: Path):
    item = _item(tmp_path)
    source = item / "RUNNING" / "work.txt"
    target = item / "TODO" / "work.txt"
    source.write_bytes(b"disposable interrupted data")
    assert requeue_running_no_clobber(str(source)) is True
    assert not source.exists()
    assert target.read_bytes() == b"disposable interrupted data"


def test_readonly_inspection_detects_conflict_without_mutation(tmp_path: Path):
    item = _item(tmp_path)
    source = item / "RUNNING" / "work.txt"
    target = item / "TODO" / "work.txt"
    source.write_bytes(b"never report running payload")
    target.write_bytes(b"never report todo payload")
    before = (source.read_bytes(), target.read_bytes())
    result = inspect_item(item)
    assert result["scan_complete"]
    assert result["counts"]["todo_running_basename_overlaps"] == 1
    assert result["counts"]["todo_running_shared_inode_groups"] == 0
    assert (source.read_bytes(), target.read_bytes()) == before
    payload = json.dumps(result)
    assert "never report" not in payload
    assert "disposable-item" not in payload


def test_readonly_inspection_rejects_symlinked_queue_role(tmp_path: Path):
    item = _item(tmp_path)
    (item / "TODO").rmdir()
    (item / "TODO").symlink_to(item / "RUNNING", target_is_directory=True)
    result = inspect_item(item)
    assert result["scan_complete"] is False
    assert result["codes"] == ["INCOMPLETE_OR_UNSAFE_SCAN"]


def test_readonly_inspection_refuses_unsafe_symlink_entry(tmp_path: Path):
    item = _item(tmp_path)
    outside = tmp_path / "external"
    outside.mkdir()
    (outside / "private.txt").write_text("NOT_A_PUBLIC_RESULT", encoding="utf-8")
    (item / "TODO" / "external-link").symlink_to(
        outside, target_is_directory=True,
    )
    result = inspect_item(item)
    assert result["scan_complete"]
    assert result["counts"]["unsafe_entries"] >= 1
    assert "UNSAFE_ENTRY_PRESENT" in result["codes"]
    assert "NOT_A_PUBLIC_RESULT" not in json.dumps(result)
