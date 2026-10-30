"""Windows-native *metadata-only* handle identity groundwork for queue inspection.

Not connected to the production inspector yet: Windows remains fail-closed
until handle-anchored directory enumeration and real Windows CI are verified.
No file payload access, name/path logging, replay or filesystem mutation.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
from pathlib import PureWindowsPath
import re


FILE_ATTRIBUTE_DIRECTORY = 0x10
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
FILE_SHARE_ALL = 0x7
FILE_LIST_DIRECTORY = 0x1
FILE_READ_ATTRIBUTES = 0x80
SYNCHRONIZE = 0x00100000
OPEN_EXISTING = 3
FILE_OPEN = 1
FILE_DIRECTORY_FILE = 0x1
FILE_NON_DIRECTORY_FILE = 0x40
FILE_SYNCHRONOUS_IO_NONALERT = 0x20
FILE_OPEN_REPARSE_POINT = 0x00200000
OBJ_CASE_INSENSITIVE = 0x40
OBJ_DONT_REPARSE = 0x1000
FILE_ID_INFO_CLASS = 18
FILE_TYPE_DISK = 1


class UnsafeWindowsIdentity(RuntimeError):
    """Fixed-code refusal with no user-provided path or filename."""


@dataclass(frozen=True)
class HandleIdentity:
    """Private process-only metadata, never serialize as operator JSON."""

    volume_serial: int
    file_id: bytes
    number_of_links: int
    is_directory: bool


class _FileIdInfo(ctypes.Structure):
    _fields_ = [
        ("VolumeSerialNumber", ctypes.c_uint64),
        ("FileId", ctypes.c_ubyte * 16),
    ]


class _ByHandleFileInfo(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTime", wintypes.FILETIME),
        ("ftLastAccessTime", wintypes.FILETIME),
        ("ftLastWriteTime", wintypes.FILETIME),
        ("dwVolumeSerialNumber", wintypes.DWORD),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
        ("nNumberOfLinks", wintypes.DWORD),
        ("nFileIndexHigh", wintypes.DWORD),
        ("nFileIndexLow", wintypes.DWORD),
    ]


class _UnicodeString(ctypes.Structure):
    _fields_ = [
        ("Length", ctypes.c_ushort),
        ("MaximumLength", ctypes.c_ushort),
        ("Buffer", ctypes.c_void_p),
    ]


class _ObjectAttributes(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.ULONG),
        ("RootDirectory", wintypes.HANDLE),
        ("ObjectName", ctypes.POINTER(_UnicodeString)),
        ("Attributes", wintypes.ULONG),
        ("SecurityDescriptor", ctypes.c_void_p),
        ("SecurityQualityOfService", ctypes.c_void_p),
    ]


class _IoStatusBlock(ctypes.Structure):
    _fields_ = [("Status", ctypes.c_void_p), ("Information", ctypes.c_size_t)]


def _require_component(component: str) -> str:
    """Allow only one literal name; reject unpaired UTF-16 surrogates safely."""
    if (
        not component or component in (".", "..")
        or component.endswith((" ", "."))
        or any(char in component for char in ("/", "\\", ":", "\x00"))
    ):
        raise UnsafeWindowsIdentity("UNSAFE_WINDOWS_COMPONENT")
    # Windows can expose unpaired UTF-16 surrogate code units. This primitive
    # intentionally refuses them rather than leaking an encoding exception,
    # or silently normalizing a path that may resolve to a different file.
    try:
        encoded_length = len(component.encode("utf-16-le"))
    except UnicodeEncodeError:
        raise UnsafeWindowsIdentity("UNSAFE_WINDOWS_COMPONENT") from None
    if encoded_length > 510:
        raise UnsafeWindowsIdentity("UNSAFE_WINDOWS_COMPONENT")
    return component


def _drive_parts(path: str | os.PathLike[str]) -> tuple[str, tuple[str, ...]]:
    """Reject drive-relative paths, UNC, device names and dotdot before opens."""
    raw = os.fspath(path)
    if not isinstance(raw, str) or "\x00" in raw:
        raise UnsafeWindowsIdentity("UNSAFE_WINDOWS_ROOT")
    # Reject device/extended paths and UNC instead of trying to reinterpret
    # a namespace with potentially different reparse/normalization behavior.
    if raw.startswith(("\\\\", "//")):
        raise UnsafeWindowsIdentity("UNSUPPORTED_WINDOWS_NAMESPACE")
    p = PureWindowsPath(raw)
    if (
        not p.is_absolute() or not re.fullmatch(r"[A-Za-z]:", p.drive)
        or p.root != "\\"
        or ".." in p.parts
    ):
        raise UnsafeWindowsIdentity("UNSAFE_WINDOWS_ROOT")
    drive = p.drive.upper()
    # PureWindowsPath folds "."; reject it at raw-component level as well.
    # A conventional C:\ root is permitted, but no path component is silently
    # resolved by following a junction.
    tail = raw.replace("/", "\\").split("\\")[1:]
    if any(x == "." or x == ".." for x in tail):
        raise UnsafeWindowsIdentity("UNSAFE_WINDOWS_ROOT")
    return drive, tuple(_require_component(x) for x in p.parts[1:])


class _WinApi:
    """Load Windows functions only upon use on a genuine Windows host."""

    def __init__(self):
        if os.name != "nt" or not hasattr(ctypes, "WinDLL"):
            raise UnsafeWindowsIdentity("WINDOWS_NATIVE_UNAVAILABLE")
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.ntdll = ctypes.WinDLL("ntdll")
        k = self.kernel32
        n = self.ntdll
        k.CreateFileW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        ]
        k.CreateFileW.restype = wintypes.HANDLE
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle.restype = wintypes.BOOL
        k.GetFileInformationByHandle.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(_ByHandleFileInfo)
        ]
        k.GetFileInformationByHandle.restype = wintypes.BOOL
        k.GetFileInformationByHandleEx.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD
        ]
        k.GetFileInformationByHandleEx.restype = wintypes.BOOL
        k.GetFileType.argtypes = [wintypes.HANDLE]
        k.GetFileType.restype = wintypes.DWORD
        n.NtCreateFile.argtypes = [
            ctypes.POINTER(wintypes.HANDLE), wintypes.ULONG,
            ctypes.POINTER(_ObjectAttributes), ctypes.POINTER(_IoStatusBlock),
            ctypes.c_void_p, wintypes.ULONG, wintypes.ULONG, wintypes.ULONG,
            wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG,
        ]
        n.NtCreateFile.restype = ctypes.c_long

    def close(self, handle):
        if handle is not None:
            self.kernel32.CloseHandle(handle)

    def open_drive_root(self, drive: str):
        # The drive root is opened once, without following its own final
        # reparse point. It is never reconstructed as a full path after this.
        handle = self.kernel32.CreateFileW(
            "\\\\?\\" + drive + "\\",
            FILE_LIST_DIRECTORY | FILE_READ_ATTRIBUTES | SYNCHRONIZE,
            FILE_SHARE_ALL, None, OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, None,
        )
        raw = getattr(handle, "value", handle)
        if raw is None or raw == ctypes.c_void_p(-1).value:
            raise UnsafeWindowsIdentity("WINDOWS_ROOT_OPEN_FAILED")
        try:
            identity = self.identity(handle)
            if not identity.is_directory:
                raise UnsafeWindowsIdentity("WINDOWS_ROOT_NOT_DIRECTORY")
            return handle
        except BaseException:
            self.close(handle)
            raise

    def open_child(self, parent, name: str, *, directory: bool):
        name = _require_component(name)
        wide = ctypes.create_unicode_buffer(name)
        encoded_length = len(name.encode("utf-16-le"))
        u = _UnicodeString(
            encoded_length, encoded_length + 2,
            ctypes.cast(wide, ctypes.c_void_p).value,
        )
        attributes = _ObjectAttributes(
            ctypes.sizeof(_ObjectAttributes), parent, ctypes.pointer(u),
            OBJ_CASE_INSENSITIVE | OBJ_DONT_REPARSE, None, None,
        )
        result = wintypes.HANDLE()
        status_block = _IoStatusBlock()
        access = FILE_READ_ATTRIBUTES | SYNCHRONIZE
        if directory:
            access |= FILE_LIST_DIRECTORY
        options = (
            FILE_SYNCHRONOUS_IO_NONALERT | FILE_OPEN_REPARSE_POINT
            | (FILE_DIRECTORY_FILE if directory else FILE_NON_DIRECTORY_FILE)
        )
        status = self.ntdll.NtCreateFile(
            ctypes.byref(result), access, ctypes.byref(attributes),
            ctypes.byref(status_block), None, 0, FILE_SHARE_ALL, FILE_OPEN,
            options, None, 0,
        )
        if status < 0 or not result.value:
            raise UnsafeWindowsIdentity("WINDOWS_CHILD_OPEN_FAILED")
        try:
            identity = self.identity(result)
            if identity.is_directory is not directory:
                raise UnsafeWindowsIdentity("WINDOWS_ENTRY_TYPE_MISMATCH")
            return result
        except BaseException:
            self.close(result)
            raise

    def identity(self, handle) -> HandleIdentity:
        if self.kernel32.GetFileType(handle) != FILE_TYPE_DISK:
            raise UnsafeWindowsIdentity("UNSUPPORTED_WINDOWS_FILE_TYPE")
        by_handle = _ByHandleFileInfo()
        if not self.kernel32.GetFileInformationByHandle(
            handle, ctypes.byref(by_handle)
        ):
            raise UnsafeWindowsIdentity("WINDOWS_HANDLE_INFO_UNAVAILABLE")
        if by_handle.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT:
            raise UnsafeWindowsIdentity("WINDOWS_REPARSE_POINT_REFUSED")
        file_id = _FileIdInfo()
        if not self.kernel32.GetFileInformationByHandleEx(
            handle, FILE_ID_INFO_CLASS, ctypes.byref(file_id),
            ctypes.sizeof(file_id),
        ):
            raise UnsafeWindowsIdentity("WINDOWS_FILE_ID_UNAVAILABLE")
        identifier = bytes(file_id.FileId)
        if (
            not file_id.VolumeSerialNumber
            or not any(identifier)
            or by_handle.nNumberOfLinks < 1
        ):
            raise UnsafeWindowsIdentity("WINDOWS_FILE_ID_UNRELIABLE")
        return HandleIdentity(
            volume_serial=int(file_id.VolumeSerialNumber),
            file_id=identifier,
            number_of_links=int(by_handle.nNumberOfLinks),
            is_directory=bool(by_handle.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY),
        )


def _walk_identity(api, drive: str, directories: tuple[str, ...],
                   leaf: str, *, leaf_is_directory: bool) -> HandleIdentity:
    """Pin every ancestor; successively open one relative name from each."""
    handles = []
    try:
        current = api.open_drive_root(drive)
        handles.append(current)
        for name in directories:
            current = api.open_child(current, name, directory=True)
            handles.append(current)
        child = api.open_child(current, leaf, directory=leaf_is_directory)
        handles.append(child)
        return api.identity(child)
    finally:
        for handle in reversed(handles):
            api.close(handle)


def probe_handle_identity(path: str | os.PathLike[str], *,
                          is_directory: bool = False) -> HandleIdentity:
    """Metadata only, with no-follow ancestors; never print the identity.

    This is NOT a queue scanner or sufficient source-generation proof.
    Only for Windows host-native acceptance and future safe enumeration.
    """
    if os.name != "nt":
        raise UnsafeWindowsIdentity("WINDOWS_NATIVE_UNAVAILABLE")
    drive, parts = _drive_parts(path)
    if not parts:
        # Item/root probes need a leaf; avoid relying on empty path handling.
        raise UnsafeWindowsIdentity("WINDOWS_LEAF_REQUIRED")
    api = _WinApi()
    return _walk_identity(api, drive, parts[:-1], parts[-1],
                          leaf_is_directory=is_directory)
