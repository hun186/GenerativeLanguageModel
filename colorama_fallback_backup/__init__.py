"""Minimal local colorama compatibility fallback for test/runtime environments.

The project only relies on color constants for terminal decoration.  Keeping
these attributes available lets non-color test environments import modules
without requiring the third-party package.
"""

class _Codes:
    BLACK = ""
    RED = ""
    GREEN = ""
    YELLOW = ""
    BLUE = ""
    MAGENTA = ""
    CYAN = ""
    WHITE = ""
    RESET = ""
    LIGHTBLACK_EX = ""
    LIGHTRED_EX = ""
    LIGHTGREEN_EX = ""
    LIGHTYELLOW_EX = ""
    LIGHTBLUE_EX = ""
    LIGHTMAGENTA_EX = ""
    LIGHTCYAN_EX = ""
    LIGHTWHITE_EX = ""


class _StyleCodes:
    BRIGHT = ""
    DIM = ""
    NORMAL = ""
    RESET_ALL = ""


Fore = _Codes()
Back = _Codes()
Style = _StyleCodes()


def init(*args, **kwargs):
    return None


def deinit():
    return None


def just_fix_windows_console():
    return None
