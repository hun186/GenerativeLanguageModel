"""Optional native process memory probe for the offline quality benchmark.

On Windows, PROCESS_MEMORY_COUNTERS.PeakWorkingSetSize is a historical
*working-set* high-water mark. This is not private committed bytes, nor does
it isolate the report call from interpreter/import baseline memory.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys


class _ProcessMemoryCounters(ctypes.Structure):
    """Windows PROCESS_MEMORY_COUNTERS (native 10-field layout)."""

    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def windows_peak_working_set_bytes() -> int | None:
    """Read this process's peak resident working set without external packages.

    On unsupported platforms or Win32 API failure return None. No system
    error messages, process IDs, paths, or diagnostics are propagated.
    """
    if sys.platform != "win32":
        return None
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)

        current_process = kernel32.GetCurrentProcess
        current_process.argtypes = []
        current_process.restype = wintypes.HANDLE

        get_info = psapi.GetProcessMemoryInfo
        get_info.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        get_info.restype = wintypes.BOOL

        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        ok = get_info(current_process(), ctypes.byref(counters), counters.cb)
        if not ok:
            return None
        peak = int(counters.PeakWorkingSetSize)
        return peak if peak > 0 else None
    except (OSError, AttributeError, TypeError, ValueError, OverflowError,
            ctypes.ArgumentError):
        return None
