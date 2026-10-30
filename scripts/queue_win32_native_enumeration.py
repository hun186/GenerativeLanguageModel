"""Bounded, handle-relative Windows directory inventory (EXPERIMENTAL).

No path-based recursion, file-content reads, mutation, error path leakage or
automatic retries. Until real Windows 3.10/3.11/NTFS tests pass, the operator
CLI keeps this strictly opt-in and always returns review_required/exit 2.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
import struct

from scripts.queue_win32_handle_identity import (
    _IoStatusBlock, _WinApi, _drive_parts, _require_component,
    FILE_ATTRIBUTE_DIRECTORY, FILE_ATTRIBUTE_REPARSE_POINT,
    UnsafeWindowsIdentity,
)

# From FILE_DIRECTORY_INFORMATION, documented structure offset 56/60/64.
FILE_DIRECTORY_INFORMATION_CLASS = 1
DIRECTORY_RECORD_HEADER = 64
DIRECTORY_QUERY_BYTES = 65536
STATUS_SUCCESS = 0x00000000
STATUS_NO_MORE_FILES = 0x80000006
STATUS_NO_SUCH_FILE = 0xC000000F
MAX_NATIVE_DEPTH = 64
ROLES = ("TODO", "RUNNING", "Success", ".success-publish-staging")


@dataclass(frozen=True)
class _Entry:
    name: str
    attributes: int


def _decode_directory_record(raw: bytes) -> _Entry:
    """Parse precisely one FILE_DIRECTORY_INFORMATION without trusting sizes."""
    if len(raw) < DIRECTORY_RECORD_HEADER:
        raise UnsafeWindowsIdentity("WINDOWS_DIRECTORY_RECORD_INVALID")
    next_offset = struct.unpack_from("<I", raw, 0)[0]
    attributes, name_bytes = struct.unpack_from("<II", raw, 56)
    if (
        next_offset != 0 or name_bytes == 0 or name_bytes & 1
        or name_bytes > 510
        or name_bytes > len(raw) - DIRECTORY_RECORD_HEADER
    ):
        raise UnsafeWindowsIdentity("WINDOWS_DIRECTORY_RECORD_INVALID")
    try:
        name = raw[DIRECTORY_RECORD_HEADER:
                   DIRECTORY_RECORD_HEADER + name_bytes].decode("utf-16-le")
    except UnicodeDecodeError:
        raise UnsafeWindowsIdentity("WINDOWS_DIRECTORY_NAME_UNSAFE") from None
    if name not in (".", ".."):
        _require_component(name)
    return _Entry(name=name, attributes=attributes)


class _NativeDirectoryApi(_WinApi):
    """NtQueryDirectoryFile uses only an existing opened directory handle."""

    def __init__(self):
        super().__init__()
        method = self.ntdll.NtQueryDirectoryFile
        method.argtypes = [
            wintypes.HANDLE, wintypes.HANDLE, ctypes.c_void_p,
            ctypes.c_void_p, ctypes.POINTER(_IoStatusBlock),
            ctypes.c_void_p, wintypes.ULONG, ctypes.c_int, wintypes.BOOLEAN,
            ctypes.c_void_p, wintypes.BOOLEAN,
        ]
        method.restype = ctypes.c_long

    def entries(self, directory_handle):
        """Stream exactly one record per call, never buffer a whole directory."""
        first = True
        while True:
            buffer = ctypes.create_string_buffer(DIRECTORY_QUERY_BYTES)
            io = _IoStatusBlock()
            status = self.ntdll.NtQueryDirectoryFile(
                directory_handle, None, None, None, ctypes.byref(io),
                ctypes.byref(buffer), DIRECTORY_QUERY_BYTES,
                FILE_DIRECTORY_INFORMATION_CLASS, True, None, bool(first),
            )
            first = False
            code = int(status) & 0xFFFFFFFF
            if code in (STATUS_NO_MORE_FILES, STATUS_NO_SUCH_FILE):
                return
            if code != STATUS_SUCCESS:
                raise UnsafeWindowsIdentity("WINDOWS_DIRECTORY_QUERY_FAILED")
            length = int(io.Information)
            if not DIRECTORY_RECORD_HEADER <= length <= DIRECTORY_QUERY_BYTES:
                raise UnsafeWindowsIdentity("WINDOWS_DIRECTORY_RECORD_INVALID")
            entry = _decode_directory_record(buffer.raw[:length])
            if entry.name not in (".", ".."):
                yield entry


def _scan_roles_with_api(api, item_dir, limit: int):
    """Injectable handle API for synthetic tests; preserve a shared item cap."""
    if not 1 <= limit <= 100000:
        raise UnsafeWindowsIdentity("INVALID_ENTRY_LIMIT")
    drive, parts = _drive_parts(item_dir)
    if not parts:
        raise UnsafeWindowsIdentity("WINDOWS_ITEM_ROOT_REQUIRED")
    handles = []
    try:
        item_handle = api.open_drive_root(drive)
        handles.append(item_handle)
        for part in parts:
            item_handle = api.open_child(item_handle, part, directory=True)
            handles.append(item_handle)

        # Bound even the item-root role discovery, and never reconstruct a
        # pathname to test whether a role exists.
        discovered = {}
        seen = [0]
        role_names = {name.casefold(): name for name in ROLES}
        for item in api.entries(item_handle):
            seen[0] += 1
            if seen[0] > limit:
                raise UnsafeWindowsIdentity("WINDOWS_SCAN_LIMIT")
            role = role_names.get(item.name.casefold())
            if role is not None:
                # Two role names differing only by casing must never be
                # quietly treated as separate queues on case-sensitive NTFS.
                if role in discovered:
                    raise UnsafeWindowsIdentity("WINDOWS_DUPLICATE_ROLE")
                discovered[role] = item

        out = {role: [] for role in ROLES}
        unsafe_count = 0

        def walk(directory_handle, prefix, role, depth):
            nonlocal unsafe_count
            if depth > MAX_NATIVE_DEPTH:
                raise UnsafeWindowsIdentity("WINDOWS_SCAN_DEPTH_LIMIT")
            for entry in api.entries(directory_handle):
                seen[0] += 1
                if seen[0] > limit:
                    raise UnsafeWindowsIdentity("WINDOWS_SCAN_LIMIT")
                if entry.attributes & FILE_ATTRIBUTE_REPARSE_POINT:
                    unsafe_count += 1
                    continue
                name = entry.name
                relative = prefix + (name,)
                is_dir = bool(entry.attributes & FILE_ATTRIBUTE_DIRECTORY)
                child = api.open_child(directory_handle, name, directory=is_dir)
                try:
                    identity = api.identity(child)
                    if identity.is_directory != is_dir:
                        raise UnsafeWindowsIdentity("WINDOWS_ENTRY_TYPE_MISMATCH")
                    if is_dir:
                        walk(child, relative, role, depth + 1)
                    else:
                        out[role].append((
                            relative, (identity.volume_serial, identity.file_id),
                            identity.number_of_links,
                        ))
                finally:
                    api.close(child)

        for role in ROLES:
            if role not in discovered:
                continue
            entry = discovered[role]
            if (entry.attributes & FILE_ATTRIBUTE_REPARSE_POINT
                    or not entry.attributes & FILE_ATTRIBUTE_DIRECTORY):
                raise UnsafeWindowsIdentity("WINDOWS_ROLE_UNSAFE")
            # Open the *listed* name through the pinned parent, not a
            # guessed canonical path that could address a different entry.
            role_handle = api.open_child(
                item_handle, entry.name, directory=True
            )
            try:
                walk(role_handle, (), role, 0)
            finally:
                api.close(role_handle)
        return out, unsafe_count, 0
    finally:
        for handle in reversed(handles):
            api.close(handle)


def scan_windows_roles(item_dir, max_entries: int):
    """Native Windows scan; NEVER call without explicit operator opt-in."""
    if os.name != "nt":
        raise UnsafeWindowsIdentity("WINDOWS_NATIVE_UNAVAILABLE")
    return _scan_roles_with_api(_NativeDirectoryApi(), os.fspath(item_dir),
                                max_entries)
