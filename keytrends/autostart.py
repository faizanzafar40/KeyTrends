"""Enable or disable launching KeyTrends when Windows starts.

Uses the per-user Run key, so no administrator rights are needed and the change
only ever affects the current account.
"""
from __future__ import annotations

import sys
from pathlib import Path

from . import config

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "KeyTrends"

try:
    import winreg
except ImportError:  # pragma: no cover - non-Windows
    winreg = None


def _launcher_command() -> str:
    """The command Windows should run at login.

    Prefers pythonw.exe so the tracker starts without a console window.
    """
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else exe
    script = Path(__file__).resolve().parent.parent / "run.py"
    return f'"{interpreter}" "{script}" --background'


def is_enabled() -> bool:
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(value)
    except FileNotFoundError:
        return False
    except OSError:
        return False


def enable() -> bool:
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _launcher_command())
        config.save({"autostart": True})
        return True
    except OSError:
        return False


def disable() -> bool:
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        pass
    except OSError:
        return False
    config.save({"autostart": False})
    return True


def set_enabled(enabled: bool) -> bool:
    return enable() if enabled else disable()
