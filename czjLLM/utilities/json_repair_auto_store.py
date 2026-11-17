# -*- coding: utf-8 -*-
"""Default project-local, owner-private JSON repair cache bootstrap.

No directory is trusted because it is merely inside the checkout. A failed
local-volume or ACL check disables raw capture; the original repair continues.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import re
import stat

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_RELATIVE_PATH = Path(".runtime-private") / "json_repair"


def _native_error(code: str) -> ValueError:
    # Do not print user names, SID, private paths or native exception messages.
    return ValueError(code)


def _win_sid_string(sid_ptr) -> str:
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    adv.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    out = wintypes.LPWSTR()
    if not adv.ConvertSidToStringSidW(sid_ptr, ctypes.byref(out)):
        raise _native_error("WINDOWS_PRIVATE_SID_UNAVAILABLE")
    try:
        return ctypes.wstring_at(out)
    finally:
        kernel.LocalFree(ctypes.cast(out, ctypes.c_void_p))


def _win_current_user_sid() -> str:
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    adv.OpenProcessToken.restype = wintypes.BOOL
    adv.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    adv.GetTokenInformation.restype = wintypes.BOOL
    token = wintypes.HANDLE()
    if not adv.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise _native_error("WINDOWS_PRIVATE_TOKEN_UNAVAILABLE")
    try:
        size = wintypes.DWORD()
        adv.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        if not 16 <= size.value <= 8192:
            raise _native_error("WINDOWS_PRIVATE_TOKEN_UNAVAILABLE")
        buffer = ctypes.create_string_buffer(size.value)
        if not adv.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            raise _native_error("WINDOWS_PRIVATE_TOKEN_UNAVAILABLE")
        pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        if not pointer:
            raise _native_error("WINDOWS_PRIVATE_TOKEN_UNAVAILABLE")
        return _win_sid_string(pointer)
    finally:
        kernel.CloseHandle(token)


def _win_volume_is_ntfs(path: Path) -> bool:
    from czjLLM.utilities.json_repair_private_capture import _windows_local_fixed_drive
    if not _windows_local_fixed_drive(path.drive):
        return False
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetVolumeInformationW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        wintypes.LPWSTR, wintypes.DWORD,
    ]
    kernel.GetVolumeInformationW.restype = wintypes.BOOL
    fs = ctypes.create_unicode_buffer(64)
    ok = kernel.GetVolumeInformationW(
        path.drive + "\\", None, 0, None, None, None, fs, len(fs),
    )
    return bool(ok and fs.value.upper() in {"NTFS", "REFS"})


def _win_private_acl(path: Path, user_sid: str) -> bool:
    """Reject inherited/world/writable-by-other ACLs; accept only owner/SYSTEM/admins."""
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    adv.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    adv.GetNamedSecurityInfoW.restype = wintypes.DWORD
    adv.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(wintypes.LPWSTR), ctypes.c_void_p,
    ]
    adv.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    descriptor = ctypes.c_void_p()
    if adv.GetNamedSecurityInfoW(str(path), 1, 4, None, None, None, None,
                                 ctypes.byref(descriptor)) != 0:
        return False
    try:
        sddl_ptr = wintypes.LPWSTR()
        if not adv.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                descriptor, 1, 4, ctypes.byref(sddl_ptr), None):
            return False
        try:
            sddl = ctypes.wstring_at(sddl_ptr)
        finally:
            kernel.LocalFree(ctypes.cast(sddl_ptr, ctypes.c_void_p))
    finally:
        kernel.LocalFree(descriptor)
    prefix, _, _ = sddl.partition("(")
    if not prefix.startswith("D:P") or set(prefix[3:]) - set("AI"):
        return False
    aces = re.findall(r"\(([^()]*)\)", sddl)
    if not aces or prefix + "".join("(" + ace + ")" for ace in aces) != sddl:
        return False
    allowed = {"SY", "BA", "S-1-5-18", "S-1-5-32-544", user_sid}
    owner_granted = False
    for ace in aces:
        parts = ace.split(";")
        if len(parts) != 6 or parts[0] != "A" or parts[2].upper() not in {"FA", "0X1F01FF"}:
            return False
        if parts[3] or parts[4] or parts[5] not in allowed:
            return False
        # Child directories and snapshot files must inherit the same restriction.
        if "OI" not in parts[1] or "CI" not in parts[1]:
            return False
        if parts[5] == user_sid:
            owner_granted = True
    return owner_granted


def _win_create_private(path: Path, user_sid: str) -> None:
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
    ]
    adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL

    class SecurityAttributes(ctypes.Structure):
        _fields_ = [("nLength", wintypes.DWORD),
                    ("lpSecurityDescriptor", ctypes.c_void_p),
                    ("bInheritHandle", wintypes.BOOL)]

    kernel.CreateDirectoryW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(SecurityAttributes)]
    kernel.CreateDirectoryW.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    descriptor = ctypes.c_void_p()
    sddl = "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;" + user_sid + ")"
    if not adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(descriptor), None):
        raise _native_error("WINDOWS_PRIVATE_ACL_CREATE_FAILED")
    try:
        attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
        if not kernel.CreateDirectoryW(str(path), ctypes.byref(attributes)):
            if ctypes.get_last_error() != 183:  # ERROR_ALREADY_EXISTS
                raise _native_error("WINDOWS_PRIVATE_DIRECTORY_CREATE_FAILED")
    finally:
        kernel.LocalFree(descriptor)


def _checked_auto_directory(path: Path, user_sid: str | None) -> None:
    try:
        if os.name == "nt":
            if not path.exists():
                _win_create_private(path, user_sid)
        else:
            path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise _native_error("PRIVATE_AUTO_DIRECTORY_UNSAFE")
    if os.name == "nt":
        if (getattr(info, "st_file_attributes", 0) &
                getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            raise _native_error("PRIVATE_AUTO_DIRECTORY_UNSAFE")
        if not _win_private_acl(path, user_sid):
            raise _native_error("WINDOWS_PRIVATE_ACL_UNVERIFIED")
    elif info.st_mode & 0o077:
        raise _native_error("PRIVATE_AUTO_DIRECTORY_PERMISSIONS")


def auto_private_root() -> Path:
    """Securely create a fixed, project-relative location; never print the path."""
    # This is intentionally based on the import location, not process cwd.
    project = PROJECT_ROOT
    from czjLLM.utilities.json_repair_private_capture import (
        _is_regular_private, _posix_local_filesystem, _root,
    )
    for parent in (project, *project.parents):
        _is_regular_private(parent, directory=True)
    if os.name == "nt":
        if not _win_volume_is_ntfs(project):
            raise _native_error("WINDOWS_PRIVATE_VOLUME_UNVERIFIED")
        sid = _win_current_user_sid()
    else:
        if not _posix_local_filesystem(project):
            raise _native_error("POSIX_LOCAL_FILESYSTEM_UNVERIFIED")
        sid = None
    base = project / ".runtime-private"
    leaf = base / "json_repair"
    _checked_auto_directory(base, sid)
    _checked_auto_directory(leaf, sid)
    return _root(leaf)
