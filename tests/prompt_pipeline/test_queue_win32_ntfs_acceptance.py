"""Real Windows/NTFS acceptance tests using only disposable pytest directories.

These tests must run on Windows, NOT just under Linux with simulated os.name.
They use no application credentials, production inputs, LLM, SQL or ES.
"""
from __future__ import annotations

import struct
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import inspect_queue_recovery_state as inspector
from scripts import queue_win32_handle_identity as identity
from scripts import queue_win32_native_enumeration as native


pytestmark = pytest.mark.skipif(
    os.name != "nt", reason="requires genuine Windows native NTFS APIs"
)


def _item(tmp_path):
    item = tmp_path / "item"
    for role in ("TODO", "RUNNING", "Success"):
        (item / role).mkdir(parents=True, exist_ok=True)
    return item


def _junction_buffer(target_path: str) -> bytes:
    """Microsoft mount-point reparse buffer, no command shell or expansion.

    Only called with a disposable test target. The actual path never enters
    a report, log, assertion message or the operator output.
    """
    # SubstituteName is an NT absolute path; both lengths exclude NUL.
    substitute = ("\\??\\" + target_path).encode("utf-16-le")
    printed = target_path.encode("utf-16-le")
    path_buffer = substitute + b"\x00\x00" + printed + b"\x00\x00"
    # REPARSE_DATA_BUFFER: common 8-byte header, 8-byte mount-point fields.
    data_length = 8 + len(path_buffer)
    if data_length > 16_000:
        pytest.fail("WINDOWS_JUNCTION_NATIVE_PATH_TOO_LONG", pytrace=False)
    return struct.pack(
        "<IHHHHHH", 0xA0000003, data_length, 0,
        0, len(substitute), len(substitute) + 2, len(printed),
    ) + path_buffer


def _junction(link: Path, target: Path):
    """Create a disposable NTFS Junction using Win32, never a subprocess.

    No PowerShell, cmd.exe, PATH search or inherited environment is needed.
    Failure is an acceptance failure with a fixed code; never skip silently.
    """
    assert not link.exists(), "WINDOWS_JUNCTION_PREEXISTING"
    assert target.is_dir(), "WINDOWS_JUNCTION_TARGET_MISSING"
    target_absolute = str(target.resolve(strict=True))
    link.mkdir()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_handle = kernel32.CreateFileW
    open_handle.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    open_handle.restype = wintypes.HANDLE
    device_io = kernel32.DeviceIoControl
    device_io.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    )
    device_io.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    # Always open the link directory itself, not the target. This is a new
    # empty directory, so it cannot initially contain a reparse point.
    handle = open_handle(
        str(link), 0x40000000, 0x00000007, None, 3,
        0x02000000 | 0x00200000, None,
    )
    if handle in (None, ctypes.c_void_p(-1).value):
        link.rmdir()
        pytest.fail("WINDOWS_JUNCTION_NATIVE_OPEN_FAILED", pytrace=False)
    try:
        raw = _junction_buffer(target_absolute)
        buffer = ctypes.create_string_buffer(raw)
        returned = wintypes.DWORD()
        # FSCTL_SET_REPARSE_POINT, synchronous call.
        ok = device_io(
            handle, 0x000900A4, ctypes.byref(buffer), len(raw),
            None, 0, ctypes.byref(returned), None,
        )
    finally:
        close_handle(handle)
    if not ok:
        link.rmdir()
        pytest.fail("WINDOWS_JUNCTION_NATIVE_SET_FAILED", pytrace=False)
    assert link.is_dir(), "WINDOWS_JUNCTION_LINK_NOT_DIRECTORY"

def _handle_count():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.GetCurrentProcess.argtypes = []
    k.GetCurrentProcess.restype = wintypes.HANDLE
    k.GetProcessHandleCount.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)
    ]
    k.GetProcessHandleCount.restype = wintypes.BOOL
    value = wintypes.DWORD()
    assert k.GetProcessHandleCount(k.GetCurrentProcess(), ctypes.byref(value))
    return int(value.value)


def _inspect(item, **kwargs):
    return inspector.inspect_item(item, experimental_windows=True, **kwargs)


def test_native_host_has_real_ntfs_filesystem_and_128bit_file_ids(tmp_path):
    # Hosted Windows uses an NTFS system/temporary drive. Require actual NTFS.
    drive = tmp_path.drive
    assert drive and len(drive) == 2 and drive[1] == ":"
    fsutil = subprocess.run(
        ["fsutil.exe", "fsinfo", "ntfsinfo", drive],
        capture_output=True, text=True, timeout=15,
    )
    assert fsutil.returncode == 0, "WINDOWS_NTFS_VOLUME_REQUIRED"
    file = tmp_path / "metadata.txt"
    file.write_bytes(b"PRIVATE_SAMPLE_BYTES")
    value = identity.probe_handle_identity(file)
    assert value.volume_serial > 0
    assert len(value.file_id) == 16 and any(value.file_id)
    assert not value.is_directory and value.number_of_links >= 1
    assert file.read_bytes() == b"PRIVATE_SAMPLE_BYTES"


def test_real_native_todo_running_hardlink_counts_and_output_privacy(tmp_path):
    item = _item(tmp_path)
    source = item / "TODO" / "SENSITIVE_DO_NOT_PRINT.txt"
    dest = item / "RUNNING" / source.name
    payload = b"SECRET_PAYLOAD_NEVER_READ_BY_SCANNER"
    source.write_bytes(payload)
    os.link(source, dest)
    before = identity.probe_handle_identity(source)
    after = identity.probe_handle_identity(dest)
    assert before == after and before.number_of_links >= 2
    result = _inspect(item)
    assert result["scan_complete"]
    assert result["status"] == "review_required"
    assert result["counts"]["todo_running_shared_inode_groups"] == 1
    assert result["counts"]["todo_running_basename_overlaps"] == 1
    assert result["counts"]["multiply_linked_queue_entries"] == 2
    assert "POSSIBLE_INTERRUPTED_LINK_MOVE" in result["codes"]
    assert "WINDOWS_EXPERIMENTAL_UNVERIFIED" in result["codes"]
    report = json.dumps(result, ensure_ascii=True)
    assert "SENSITIVE_DO_NOT_PRINT" not in report
    assert "SECRET_PAYLOAD" not in report
    assert str(item) not in report
    assert source.read_bytes() == dest.read_bytes() == payload


def test_real_native_casefold_overlap_does_not_fabricate_shared_inode(tmp_path):
    item = _item(tmp_path)
    (item / "TODO" / "CaseName.txt").write_bytes(b"one")
    (item / "RUNNING" / "casename.txt").write_bytes(b"two")
    result = _inspect(item)
    assert result["scan_complete"]
    assert result["counts"]["todo_running_basename_overlaps"] == 1
    assert result["counts"]["todo_running_shared_inode_groups"] == 0
    assert "POSSIBLE_INTERRUPTED_LINK_MOVE" not in result["codes"]


def test_real_native_staging_orphan_is_never_treated_as_success(tmp_path):
    item = _item(tmp_path)
    staging = item / ".success-publish-staging"
    staging.mkdir()
    (staging / ".success-recovery.tmp").write_bytes(b"KEEP_ORPHAN")
    result = _inspect(item)
    assert result["scan_complete"]
    assert result["counts"]["staging_files"] == 1
    assert result["counts"]["staging_temp_files"] == 1
    assert result["counts"]["success_files"] == 0
    assert "STAGING_TEMP_PRESENT" in result["codes"]
    assert (staging / ".success-recovery.tmp").read_bytes() == b"KEEP_ORPHAN"


def test_default_windows_cli_refuses_without_opening_native_scanner(tmp_path):
    item = _item(tmp_path)
    result = inspector.inspect_item(item)
    assert result["codes"] == ["UNSUPPORTED_SAFE_SCAN_PLATFORM"]
    assert not result["scan_complete"]
    assert result["status"] == "review_required"


def test_real_ntfs_child_junction_is_counted_but_never_traversed(tmp_path):
    item = _item(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    secret = external / "PRIVATE_OUTSIDE.txt"
    secret.write_bytes(b"PRIVATE_OUTSIDE_DATA")
    junction = item / "TODO" / "junction"
    _junction(junction, external)
    try:
        result = _inspect(item)
        assert result["scan_complete"], "WINDOWS_JUNCTION_SCAN_INCOMPLETE"
        assert result["counts"]["unsafe_entries"] == 1, "WINDOWS_JUNCTION_UNSAFE_COUNT"
        assert result["counts"]["todo_files"] == 0, "WINDOWS_JUNCTION_TODO_COUNT"
        assert "UNSAFE_ENTRY_PRESENT" in result["codes"], "WINDOWS_JUNCTION_CODE_MISSING"
        assert "PRIVATE_OUTSIDE" not in json.dumps(result), "WINDOWS_JUNCTION_REPORT_LEAK"
        assert secret.read_bytes() == b"PRIVATE_OUTSIDE_DATA", "WINDOWS_JUNCTION_TARGET_CHANGED"
    finally:
        try:
            os.rmdir(junction)
        except OSError:
            pytest.fail("WINDOWS_JUNCTION_CLEANUP_FAILED", pytrace=False)

def test_junction_setup_handles_shell_metacharacters_without_expansion(tmp_path):
    special = tmp_path / "A&B_%TEMP%_^_!_$"
    special.mkdir()
    external = special / "target&outside"
    external.mkdir()
    marker = external / "do_not_traverse.txt"
    marker.write_bytes(b"NO_CMD_EXPANSION_OR_TRAVERSAL")
    item = _item(special)
    junction = item / "TODO" / "literal&%TEMP%^!"
    _junction(junction, external)
    try:
        result = _inspect(item)
        assert result["scan_complete"]
        assert result["counts"]["unsafe_entries"] == 1
        assert result["counts"]["todo_files"] == 0
        assert result["status"] == "review_required"
        assert "A&B" not in json.dumps(result)
        assert marker.read_bytes() == b"NO_CMD_EXPANSION_OR_TRAVERSAL"
    finally:
        os.rmdir(junction)


def test_real_ntfs_role_junction_fails_closed(tmp_path):
    item = _item(tmp_path)
    outside = tmp_path / "external"
    outside.mkdir()
    (item / "TODO").rmdir()
    junction = item / "TODO"
    _junction(junction, outside)
    try:
        result = _inspect(item)
        assert not result["scan_complete"]
        assert result["codes"] == ["INCOMPLETE_OR_UNSAFE_SCAN"]
    finally:
        os.rmdir(junction)


def test_real_ntfs_ancestor_junction_is_rejected_not_followed(tmp_path):
    item = _item(tmp_path)
    external = tmp_path / "outside"
    external.mkdir()
    alias = tmp_path / "alias"
    _junction(alias, item)
    try:
        result = _inspect(alias)
        assert not result["scan_complete"]
        assert result["codes"] == ["INCOMPLETE_OR_UNSAFE_SCAN"]
        with pytest.raises(identity.UnsafeWindowsIdentity):
            identity.probe_handle_identity(alias, is_directory=True)
    finally:
        os.rmdir(alias)


def test_native_directory_entry_swap_to_junction_is_fail_closed(
    monkeypatch, tmp_path
):
    """Force the race after NtQueryDirectoryFile metadata, before open_child."""
    item = _item(tmp_path)
    victim = item / "TODO" / "target"
    victim.mkdir()
    external = tmp_path / "outside"
    external.mkdir()
    marker = external / "do_not_read.txt"
    marker.write_bytes(b"NEVER_OPEN_EXTERNAL")
    displaced = item / "TODO" / "displaced"
    original_entries = native._NativeDirectoryApi.entries
    switched = [False]

    def race_entries(self, handle):
        for entry in original_entries(self, handle):
            if entry.name == "target" and not switched[0]:
                switched[0] = True
                victim.rename(displaced)
                _junction(victim, external)
            yield entry

    monkeypatch.setattr(native._NativeDirectoryApi, "entries", race_entries)
    try:
        result = _inspect(item)
        assert switched[0], "WINDOWS_NATIVE_RACE_TEST_NOT_EXERCISED"
        assert not result["scan_complete"]
        assert result["codes"] == ["INCOMPLETE_OR_UNSAFE_SCAN"]
        assert marker.read_bytes() == b"NEVER_OPEN_EXTERNAL"
    finally:
        # Path.is_junction() only exists in Python 3.12+. rmdir() removes
        # a temporary junction or empty directory without following it.
        if victim.exists():
            os.rmdir(victim)


def test_real_ntfs_entry_limit_is_fail_closed_without_partial_counts(tmp_path):
    item = _item(tmp_path)
    for i in range(12):
        (item / "TODO" / f"segment{i:03}.txt").write_bytes(b"secret")
    result = _inspect(item, max_entries=5)
    assert not result["scan_complete"]
    assert result["codes"] == ["INCOMPLETE_OR_UNSAFE_SCAN"]
    assert all(x == 0 for x in result["counts"].values())


def test_windows_handle_count_stable_across_repeated_native_scans(tmp_path):
    item = _item(tmp_path)
    (item / "TODO" / "nested").mkdir()
    (item / "TODO" / "nested" / "piece.txt").write_bytes(b"PRIVATE")
    before = _handle_count()
    for _ in range(45):
        report = _inspect(item)
        assert report["scan_complete"]
        assert report["status"] == "review_required"
        assert "WINDOWS_EXPERIMENTAL_UNVERIFIED" in report["codes"]
    after = _handle_count()
    assert after - before <= 8, "WINDOWS_NATIVE_HANDLE_LEAK_SUSPECTED"


def test_direct_script_opt_in_is_still_review_required_exit_two(tmp_path):
    item = _item(tmp_path)
    script = Path(inspector.__file__).resolve()
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    proc = subprocess.run(
        [sys.executable, str(script), "--item-dir", str(item),
         "--experimental-windows"],
        cwd=tmp_path, env=env, capture_output=True, text=True,
        timeout=30,
    )
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr
    data = json.loads(proc.stdout)
    assert data["all_snapshots_complete"]
    assert data["manual_review_required"]
    assert data["items"][0]["status"] == "review_required"
    assert "WINDOWS_EXPERIMENTAL_UNVERIFIED" in data["items"][0]["codes"]
