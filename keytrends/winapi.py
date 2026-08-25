"""Thin ctypes wrappers around the Win32 calls KeyTrends needs.

Every function degrades gracefully: on a non-Windows platform, or if a call
fails, the caller gets a neutral value instead of an exception.
"""
from __future__ import annotations

import ctypes
import sys
import time

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import ctypes.wintypes as wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _LastInputInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    try:
        import psutil
    except ImportError:  # pragma: no cover - psutil is a hard requirement in practice
        psutil = None
else:  # pragma: no cover - the app targets Windows
    psutil = None


def idle_seconds() -> float:
    """Seconds since the last system-wide keyboard or mouse input."""
    if not IS_WINDOWS:
        return 0.0
    try:
        info = _LastInputInfo()
        info.cbSize = ctypes.sizeof(_LastInputInfo)
        if not _user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        # GetTickCount64 avoids the 49.7-day wraparound of the 32-bit version.
        now = _kernel32.GetTickCount64()
        return max(0.0, (now - info.dwTime) / 1000.0)
    except Exception:
        return 0.0


_cached_app = ("", 0.0)
_APP_CACHE_SECONDS = 0.5


def foreground_app() -> str:
    """Process name of the focused window, e.g. 'chrome'.

    Result is cached briefly because this runs on every input event.
    """
    global _cached_app
    if not IS_WINDOWS or psutil is None:
        return ""
    name, stamp = _cached_app
    now = time.monotonic()
    if now - stamp < _APP_CACHE_SECONDS:
        return name
    try:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return name
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return name
        proc = psutil.Process(pid.value).name()
        if proc.lower().endswith(".exe"):
            proc = proc[:-4]
        _cached_app = (proc, now)
        return proc
    except Exception:
        _cached_app = (name, now)
        return name


def screen_size() -> tuple[int, int]:
    """Primary display resolution in pixels."""
    if not IS_WINDOWS:
        return (1920, 1080)
    try:
        return (_user32.GetSystemMetrics(0), _user32.GetSystemMetrics(1))
    except Exception:
        return (1920, 1080)
