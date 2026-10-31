"""Real-filesystem tests for read-only, path-free queue recovery inspection."""
import json
import os
from pathlib import Path
import sys

import pytest

from scripts import inspect_queue_recovery_state as diagnostic


@pytest.fixture(autouse=True)
def _skip_unsupported_platform_except_fail_closed_tests(request):
    # Windows 3.10/3.11 must REJECT traversal; only the explicit unsupported
    # platform and static reparse-metadata tests run there. Do not weaken the
    # scanner to make filesystem-success tests pass on Windows.
    unsupported_cases = {
        "test_unsupported_windows_safe_fd_scan_fails_closed",
        "test_windows_junction_reparse_metadata_is_considered_unsafe",
    }
    if (request.node.name not in unsupported_cases
            and not diagnostic._supports_safe_scan()):
        pytest.skip("safe descriptor-relative nofollow traversal unavailable")


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

def test_unsupported_windows_safe_fd_scan_fails_closed(tmp_path, monkeypatch):
    item = _item(tmp_path)
    (item / "TODO" / "sample.txt").write_text("not examined")
    monkeypatch.setattr(diagnostic, "_supports_safe_scan", lambda: False)
    def forbidden(*_args, **_kwargs):
        raise AssertionError("unsafe Windows path traversal attempted")
    monkeypatch.setattr(diagnostic.os, "scandir", forbidden)
    result = diagnostic.inspect_item(item)
    assert result["status"] == "review_required"
    assert not result["scan_complete"]
    assert result["codes"] == ["UNSUPPORTED_SAFE_SCAN_PLATFORM"]


def test_windows_junction_reparse_metadata_is_considered_unsafe():
    from types import SimpleNamespace
    assert diagnostic._is_reparse_point(
        SimpleNamespace(st_file_attributes=0x400)
    )
    assert not diagnostic._is_reparse_point(
        SimpleNamespace(st_file_attributes=0)
    )


def test_zero_windows_inode_placeholders_are_never_equated(tmp_path, monkeypatch):
    from types import SimpleNamespace
    item = _item(tmp_path)
    for role in ("TODO", "RUNNING"):
        (item / role / "root.txt").write_text(role)
    real_stat = os.stat
    def placeholder_stat(path, *args, **kwargs):
        info = real_stat(path, *args, **kwargs)
        if path == "root.txt" and kwargs.get("dir_fd") is not None:
            return SimpleNamespace(
                st_mode=info.st_mode, st_dev=0, st_ino=0, st_nlink=0,
            )
        return info
    # os.supports_dir_fd and supports_follow_symlinks contain the original
    # built-in, so monkeypatching os.stat otherwise disables the capability
    # gate and misses the regression entirely.
    supported = diagnostic._supports_safe_scan()
    monkeypatch.setattr(diagnostic.os, "stat", placeholder_stat)
    monkeypatch.setattr(diagnostic, "_supports_safe_scan", lambda: supported)
    result = diagnostic.inspect_item(item)
    assert result["scan_complete"]
    assert result["counts"]["unknown_identity_entries"] == 2
    assert result["counts"]["todo_running_shared_inode_groups"] == 0
    assert result["counts"]["multiply_linked_queue_entries"] == 0
    assert "UNKNOWN_FILE_IDENTITY" in result["codes"]
    assert "POSSIBLE_INTERRUPTED_LINK_MOVE" not in result["codes"]


def test_replacement_with_symlink_cannot_redirect_directory_scan(tmp_path, monkeypatch):
    if not diagnostic._supports_safe_scan():
        pytest.skip("handle relative nofollow not supported")
    item = _item(tmp_path)
    outside = tmp_path / "external-private"
    outside.mkdir()
    (outside / "secret.txt").write_text("TOP_SECRET")
    real_open = diagnostic._open_directory
    triggered = [False]

    def swap_directory(parent_fd, name):
        if name == "TODO" and not triggered[0]:
            triggered[0] = True
            (item / "TODO").rename(item / "TODO-original")
            (item / "TODO").symlink_to(outside, target_is_directory=True)
        return real_open(parent_fd, name)

    monkeypatch.setattr(diagnostic, "_open_directory", swap_directory)
    result = diagnostic.inspect_item(item)
    assert triggered[0]
    assert result["status"] == "review_required"
    assert result["codes"] == ["INCOMPLETE_OR_UNSAFE_SCAN"]
    assert "TOP_SECRET" not in json.dumps(result)


def test_budget_applied_during_scandir_iteration_not_after_materializing(
    tmp_path, monkeypatch,
):
    if not diagnostic._supports_safe_scan():
        pytest.skip("handle relative nofollow not supported")
    from types import SimpleNamespace
    item = _item(tmp_path)
    (item / "TODO" / "sample.txt").write_text("unread private")
    real_scandir = os.scandir
    observations = [0]

    class OverwideIterator:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def __iter__(self):
            return self
        def __next__(self):
            if observations[0] == 1000:
                raise StopIteration
            observations[0] += 1
            return SimpleNamespace(name="sample.txt")

    todo_stat = (item / "TODO").stat()

    def guarded_scandir(fd):
        # Compare directory handles instead of relying on Linux-only /proc.
        # macOS and other supported POSIX systems can exercise this test.
        if isinstance(fd, int):
            opened = os.fstat(fd)
            if ((opened.st_dev, opened.st_ino)
                    == (todo_stat.st_dev, todo_stat.st_ino)):
                return OverwideIterator()
        return real_scandir(fd)

    supported = diagnostic._supports_safe_scan()
    monkeypatch.setattr(diagnostic.os, "scandir", guarded_scandir)
    monkeypatch.setattr(diagnostic, "_supports_safe_scan", lambda: supported)
    result = diagnostic.inspect_item(item, max_entries=2)
    assert result["status"] == "review_required"
    assert result["codes"] == ["INCOMPLETE_OR_UNSAFE_SCAN"]
    assert observations[0] == 3  # cap + first overflow, never all 1000


def test_directory_enumeration_uses_fd_and_not_direntry_stat(
    tmp_path, monkeypatch,
):
    if not diagnostic._supports_safe_scan():
        pytest.skip("handle relative nofollow not supported")
    from types import SimpleNamespace
    item = _item(tmp_path)
    (item / "TODO" / "source.txt").write_text("private")
    real_scandir = os.scandir
    real_stat = os.stat
    nofollow_stats = [0]

    class Entry:
        def __init__(self, name):
            self.name = name
        def stat(self, **_kwargs):
            raise AssertionError("unreliable DirEntry.stat used")

    class Wrapped:
        def __init__(self, original):
            self.original = original
        def __enter__(self):
            self.original.__enter__()
            return self
        def __exit__(self, *args):
            return self.original.__exit__(*args)
        def __iter__(self):
            return (Entry(x.name) for x in self.original)

    def wrapped_scandir(fd):
        if isinstance(fd, int):
            return Wrapped(real_scandir(fd))
        raise AssertionError("path-based scan not allowed")

    def tracked_stat(path, *args, **kwargs):
        if kwargs.get("dir_fd") is not None:
            assert kwargs.get("follow_symlinks") is False
            nofollow_stats[0] += 1
        return real_stat(path, *args, **kwargs)

    supported = diagnostic._supports_safe_scan()
    monkeypatch.setattr(diagnostic.os, "scandir", wrapped_scandir)
    monkeypatch.setattr(diagnostic.os, "stat", tracked_stat)
    monkeypatch.setattr(diagnostic, "_supports_safe_scan", lambda: supported)
    result = diagnostic.inspect_item(item)
    assert result["status"] == "no_observed_conflicts"
    assert nofollow_stats[0] > 0


def test_dotdot_path_fails_closed_before_symlink_ancestor_normalization(tmp_path):
    item = _item(tmp_path)
    external = tmp_path / "outside"
    external.mkdir()
    (external / "private.txt").write_text("secret")
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    # abspath() would silently rewrite alias/../item as item before verifying
    # that alias is a symlink or that it would resolve outside our directory.
    disguised_item = tmp_path / "alias" / ".." / item.name
    assert ".." in disguised_item.parts
    result = diagnostic.inspect_item(disguised_item)
    assert result["scan_complete"] is False
    assert result["codes"] == ["INCOMPLETE_OR_UNSAFE_SCAN"]
    assert result["status"] == "review_required"


def test_dotdot_path_fails_closed_even_if_parent_component_missing(tmp_path):
    item = _item(tmp_path)
    disguised_item = tmp_path / "nonexistent" / ".." / item.name
    assert ".." in disguised_item.parts
    result = diagnostic.inspect_item(disguised_item)
    assert result["scan_complete"] is False
    assert result["codes"] == ["INCOMPLETE_OR_UNSAFE_SCAN"]
    assert item.is_dir()


def test_relative_dotdot_rejected_and_normal_relative_path_supported(
    tmp_path, monkeypatch,
):
    item = _item(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = diagnostic.inspect_item(Path("other") / ".." / "item")
    assert result["codes"] == ["INCOMPLETE_OR_UNSAFE_SCAN"]
    safe = diagnostic.inspect_item(Path("item"))
    assert safe["scan_complete"] is True
    assert safe["status"] == "no_observed_conflicts"


def test_blocked_recovery_status_visible_without_sensitive_paths(tmp_path):
    from czjLLM.prompt_pipeline.runtime_support.prompt_queue import (
        mark_recovery_blocked,
    )
    item = _item(tmp_path)
    (item / "RUNNING" / "secret.txt").write_text(
        "PRIVATE_NEVER_REPORT", encoding="utf-8",
    )
    mark_recovery_blocked(item, "TODO_CONFLICT", 1)
    result = diagnostic.inspect_item(item)
    assert result["scan_complete"]
    assert result["status"] == "review_required"
    assert result["recovery_integrity"] == "incomplete"
    assert result["recovery_manual_review_required"] is True
    assert result["recovery_code"] == "TODO_CONFLICT"
    assert "RECOVERY_ITEM_BLOCKED" in result["codes"]
    raw = json.dumps(result)
    assert "PRIVATE_NEVER_REPORT" not in raw
    assert "secret.txt" not in raw
    assert str(tmp_path) not in raw


def test_corrupt_recovery_marker_cannot_look_clean(tmp_path):
    item = _item(tmp_path)
    status = item / "_extract_slice_identity" / "queue_recovery_status.json"
    status.parent.mkdir()
    status.write_text('{"version":1,"state":"healthy"}', encoding="utf-8")
    result = diagnostic.inspect_item(item)
    assert not result["scan_complete"]
    assert result["recovery_integrity"] == "unknown"
    assert result["recovery_manual_review_required"] is True
    assert "UNREADABLE_RECOVERY_MARKER" in result["codes"]


def test_fifo_recovery_status_diagnostic_fails_closed_without_hang(tmp_path):
    """Codex P2: read-only status must never wait for a FIFO writer."""
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO unavailable")
    item = _item(tmp_path)
    marker = item / "_extract_slice_identity" / "queue_recovery_status.json"
    marker.parent.mkdir()
    os.mkfifo(marker)
    result = diagnostic.inspect_item(item)
    assert result["scan_complete"] is False
    assert result["recovery_integrity"] == "unknown"
    assert result["recovery_manual_review_required"] is True
    assert "UNREADABLE_RECOVERY_MARKER" in result["codes"]
