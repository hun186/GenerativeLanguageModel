# -*- coding: utf-8 -*-
"""Keep normal Win32 JSON viewer frames above their own application owner.

Tk transient windows lose native maximize controls on Windows. Attach the
normal, already-created HWND wrapper to its immediate owner instead. This
changes only the app-local Z order, never the global topmost/focus state.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import tkinter as tk


def _win32_frame_handles(win, owner):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    get_ancestor = user32.GetAncestor
    get_ancestor.argtypes = (wintypes.HWND, wintypes.UINT)
    get_ancestor.restype = wintypes.HWND
    # winfo_id is Tk's client HWND, not the outer Win32 top-level wrapper.
    # GA_ROOT follows parent links only, not the owner chain.
    frame = get_ancestor(win.winfo_id(), 2)
    owner_frame = get_ancestor(owner.winfo_id(), 2)
    if not frame or not owner_frame or frame == owner_frame:
        raise OSError("JSON viewer frame unavailable")
    return user32, frame, owner_frame


def _attach_win32_owner(win, owner):
    user32, frame, owner_frame = _win32_frame_handles(win, owner)
    get_window = user32.GetWindow
    get_window.argtypes = (wintypes.HWND, wintypes.UINT)
    get_window.restype = wintypes.HWND
    # GW_OWNER = 4, GWLP_HWNDPARENT = -8. On top-level windows this sets
    # ownership, not child parenting. Preserve the existing window styles.
    if get_window(frame, 4) == owner_frame:
        return
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        set_owner = user32.SetWindowLongPtrW
    else:
        set_owner = user32.SetWindowLongW
    set_owner.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t)
    set_owner.restype = ctypes.c_ssize_t
    ctypes.set_last_error(0)
    previous = set_owner(frame, -8, owner_frame)
    error = ctypes.get_last_error()
    if not previous and error:
        raise ctypes.WinError(error)
    if get_window(frame, 4) != owner_frame:
        raise OSError("JSON viewer owner verification failed")


def retain_win32_viewer_owner(win, owner):
    """Attach after mapping; a native failure falls back to the old popup.

    Never use global topmost, a modal grab, or a recurring focus/raise timer.
    The fallback prioritizes keeping the owner from covering the viewer.
    """
    try:
        win.update_idletasks()
        _attach_win32_owner(win, owner)
    except (OSError, tk.TclError):
        if win.winfo_exists():
            win.state("normal")
            win.transient(owner)
        return False
    return True


def main_window_has_focus(root):
    """Only the main window's own widgets may open its hover tooltips."""
    try:
        focused = root.focus_displayof()
        return focused is not None and focused.winfo_toplevel() == root
    except (tk.TclError, KeyError):
        return False
