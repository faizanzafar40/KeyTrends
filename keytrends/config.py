"""Paths and persisted user settings for KeyTrends."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

APP_NAME = "KeyTrends"


def _data_dir() -> Path:
    """Where the database and settings live.

    KEYTRENDS_DATA_DIR overrides the default, which keeps test runs and demo
    data out of the real profile.
    """
    override = os.environ.get("KEYTRENDS_DATA_DIR")
    base = Path(override) if override else Path(
        os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    ) / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


DATA_DIR = _data_dir()
DB_PATH = DATA_DIR / "keytrends.db"
SETTINGS_PATH = DATA_DIR / "settings.json"
EXPORT_DIR = DATA_DIR / "exports"

# How often the in-memory counters are written to SQLite.
FLUSH_INTERVAL_SECONDS = 5
# No input for this long means the seconds stop counting as "active".
IDLE_THRESHOLD_SECONDS = 60
# Two left clicks inside this window (and within DOUBLE_CLICK_PX) count as a double click.
DOUBLE_CLICK_MS = 400
DOUBLE_CLICK_PX = 6
# Rolling window used for the live words-per-minute reading.
WPM_WINDOW_SECONDS = 60
# Standard: one "word" is five characters.
CHARS_PER_WORD = 5

DEFAULTS = {
    "host": "127.0.0.1",
    "port": 8731,
    "paused": False,
    # When false, only aggregate totals are kept -- no per-key frequency table,
    # so the keyboard heatmap and top-keys panels stay empty.
    "track_key_detail": True,
    "track_apps": True,
    "track_shortcuts": True,
    "open_dashboard_on_start": True,
    "autostart": False,
    "milestone_notifications": True,
    # Process names that are never recorded (case-insensitive, no .exe needed).
    "excluded_apps": [],
}

_lock = threading.RLock()
_cache: dict | None = None


def load() -> dict:
    """Read settings from disk, filling in any missing keys with defaults."""
    global _cache
    with _lock:
        if _cache is None:
            data = dict(DEFAULTS)
            if SETTINGS_PATH.exists():
                try:
                    data.update(json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    pass  # Corrupt or unreadable file -- fall back to defaults.
            _cache = data
        return dict(_cache)


def save(updates: dict) -> dict:
    """Merge `updates` into the stored settings and persist them."""
    global _cache
    with _lock:
        data = load()
        data.update(updates)
        _cache = data
        tmp = SETTINGS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(SETTINGS_PATH)
        return dict(data)


def get(key: str):
    return load().get(key, DEFAULTS.get(key))
