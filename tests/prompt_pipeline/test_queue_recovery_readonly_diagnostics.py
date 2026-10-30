"""Real-filesystem tests for read-only, path-free queue recovery inspection."""
import json
import os
from pathlib import Path
import sys

import pytest

from scripts import inspect_queue_recovery_state as diagnostic


def _item(tmp_path):
    item = tmp_path / "item"
    for role in ("TODO", "RUNNING", "Success"):
        (item / role).mkdir(parents=True, exist_ok=True)
    return item


def test_empty_and_unrelated_files_are_not_falsely_reported(tmp_path):
    item = _item(tmp_path)
    (item / "TODO" / "a.txt").write_text("private pending")
    (item / "RUNNING" / "b.txt").write_text("private running")
    (item / "Success" / "c.txt").write_text("private answer")
    result = diagnostic.inspect_item(item)
    assert result["scan_complete"]
    assert result["status"] == "no_observed_conflicts"
    assert result["codes"] == []
    assert result["counts"]["todo_files"] == 1
    assert result["counts"]["running_files"] == 1
    assert result["counts"]["success_files"] == 1


def test_exact_interrupted_hardlink_pair_detected_without_changes(tmp_path):
    item = _item(tmp_path)
    source = item / "RUNNING" / "private.txt"
    source.write_bytes(b"SECRET_PROMPT_PAYLOAD")
    target = item / "TODO" / "private.txt"
    try:
        os.link(source, target)
    except OSError:
        pytest.skip("hardlinks not supported")
    before = (source.stat(), target.stat())
    result = diagnostic.inspect_item(item)
    after = (source.stat(), target.stat())
    assert result["counts"]["todo_running_shared_inode_groups"] == 1
    assert result["counts"]["multiply_linked_queue_entries"] >= 2
    assert "POSSIBLE_INTERRUPTED_LINK_MOVE" in result["codes"]
    assert "MULTILINK_QUEUE_ENTRY" in result["codes"]
    assert before[0].st_ino == after[0].st_ino
    assert before[1].st_ino == after[1].st_ino
    assert source.read_bytes() == target.read_bytes() == b"SECRET_PROMPT_PAYLOAD"
    assert "SECRET_PROMPT_PAYLOAD" not in json.dumps(result)


def test_same_basename_different_inodes_not_called_interrupted_move(tmp_path):
    item = _item(tmp_path)
    (item / "TODO" / "one.txt").write_bytes(b"new source")
    (item / "RUNNING" / "one.txt").write_bytes(b"old source")
    result = diagnostic.inspect_item(item)
    assert result["counts"]["todo_running_basename_overlaps"] == 1
    assert result["counts"]["todo_running_shared_inode_groups"] == 0
    assert "POSSIBLE_INTERRUPTED_LINK_MOVE" not in result["codes"]


def test_nested_duplicate_todo_and_existing_success_are_counted(tmp_path):
    item = _item(tmp_path)
    for name in ("nested1", "nested2"):
        (item / "TODO" / name).mkdir()
        (item / "TODO" / name / "duplicate.txt").write_text("input")
    (item / "Success" / "duplicate.txt").write_text("old answer")
    result = diagnostic.inspect_item(item)
    assert result["counts"]["duplicate_todo_basename_groups"] == 1
    assert result["counts"]["todo_success_basename_overlaps"] == 1
    assert "DUPLICATE_TODO_BASENAME" in result["codes"]
    assert "TODO_SUCCESS_CONFLICT" in result["codes"]


def test_running_success_overlap_not_claimed_complete(tmp_path):
    item = _item(tmp_path)
    (item / "RUNNING" / "same.txt").write_text("input")
    (item / "Success" / "same.txt").write_text("output")
    result = diagnostic.inspect_item(item)
    assert result["counts"]["running_success_basename_overlaps"] == 1
    assert "RUNNING_SUCCESS_OVERLAP" in result["codes"]
    assert result["status"] == "review_required"


def test_staging_orphan_outside_success_is_visible_without_content(tmp_path):
    item = _item(tmp_path)
    stage = item / ".success-publish-staging"
    stage.mkdir()
    staged = stage / ".success-private.tmp"
    staged.write_bytes(b"SECRET_COMMITTED_RESPONSE")
    result = diagnostic.inspect_item(item)
    assert result["counts"]["staging_temp_files"] == 1
    assert result["counts"]["success_files"] == 0
    assert "STAGING_TEMP_PRESENT" in result["codes"]
    assert staged.read_bytes() == b"SECRET_COMMITTED_RESPONSE"
    assert "SECRET_COMMITTED_RESPONSE" not in json.dumps(result)


def test_symlinks_never_followed_and_signal_unsafe(tmp_path):
    item = _item(tmp_path)
    outside = tmp_path / "outside-private"
    outside.mkdir()
    (outside / "secret.txt").write_text("NEVER_OUTPUT_THIS")
    try:
        (item / "TODO" / "linked").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    result = diagnostic.inspect_item(item)
    assert result["scan_complete"]
    assert result["counts"]["unsafe_entries"] == 1
    assert "UNSAFE_ENTRY_PRESENT" in result["codes"]
    assert "NEVER_OUTPUT_THIS" not in json.dumps(result)


def test_symlinked_role_directory_fails_closed(tmp_path):
    item = _item(tmp_path)
    (item / "TODO").rmdir()
    try:
        (item / "TODO").symlink_to(item / "RUNNING", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    result = diagnostic.inspect_item(item)
    assert not result["scan_complete"]
    assert result["codes"] == ["INCOMPLETE_OR_UNSAFE_SCAN"]


def test_missing_or_symlink_item_root_fails_closed(tmp_path):
    item = _item(tmp_path)
    missing = diagnostic.inspect_item(tmp_path / "missing")
    assert missing["status"] == "review_required"
    assert not missing["scan_complete"]
    try:
        alias = tmp_path / "alias"
        alias.symlink_to(item, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    result = diagnostic.inspect_item(alias)
    assert not result["scan_complete"]


def test_entry_limit_fails_closed_without_partial_clear_claim(tmp_path):
    item = _item(tmp_path)
    for num in range(3):
        (item / "TODO" / f"slice{num}.txt").write_text("content")
    result = diagnostic.inspect_item(item, max_entries=2)
    assert result["scan_complete"] is False
    assert result["status"] == "review_required"
    assert result["codes"] == ["INCOMPLETE_OR_UNSAFE_SCAN"]


def test_cli_reports_only_ordinals_and_fixed_counts_not_paths(tmp_path, monkeypatch, capsys):
    secret_root = tmp_path / "PRIVATE_HOST_AND_USER"
    secret_root.mkdir()
    item = _item(secret_root)
    (item / "TODO" / "PRIVATE_CREDENTIAL_NAME.txt").write_text(
        "SENSITIVE_INPUT_CONTENT"
    )
    (item / "Success" / "PRIVATE_CREDENTIAL_NAME.txt").write_text("result")
    monkeypatch.setattr(sys, "argv", [
        "queue-inspect", "--item-dir", str(item),
    ])
    exit_code = diagnostic.main()
    stdout = capsys.readouterr().out
    report = json.loads(stdout)
    assert exit_code == 2
    assert report["items"][0]["item"] == 1
    assert report["items"][0]["status"] == "review_required"
    assert "TODO_SUCCESS_CONFLICT" in report["items"][0]["codes"]
    for private in ("PRIVATE_HOST_AND_USER", "PRIVATE_CREDENTIAL_NAME",
                    "SENSITIVE_INPUT_CONTENT", str(item)):
        assert private not in stdout


def test_cli_clear_is_zero_but_explicitly_non_authoritative(tmp_path, monkeypatch, capsys):
    item = _item(tmp_path)
    monkeypatch.setattr(sys, "argv", ["queue-inspect", "--item-dir", str(item)])
    assert diagnostic.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["all_snapshots_complete"] is True
    assert report["manual_review_required"] is False
    assert report["mode"] == "read_only_non_atomic"
    assert "does not prove completion" in report["warning"]


def test_multiple_items_indices_only_and_first_item_incomplete(tmp_path):
    first = tmp_path / "missing"
    second = _item(tmp_path / "second")
    report = diagnostic.inspect_items([first, second])
    assert not report["all_snapshots_complete"]
    assert report["manual_review_required"]
    assert [row["item"] for row in report["items"]] == [1, 2]
    assert report["items"][0]["scan_complete"] is False
    assert report["items"][1]["scan_complete"] is True
    assert "second" not in json.dumps(report)


def test_no_regular_source_contents_are_read(tmp_path, monkeypatch):
    item = _item(tmp_path)
    (item / "RUNNING" / "slice.txt").write_text("secret")
    def never_read(*args, **kwargs):
        raise AssertionError("queue content read")
    monkeypatch.setattr(Path, "read_bytes", never_read)
    monkeypatch.setattr(Path, "read_text", never_read)
    assert diagnostic.inspect_item(item)["counts"]["running_files"] == 1

