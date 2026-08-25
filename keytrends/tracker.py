"""The input tracker.

Listens for global keyboard and mouse events, keeps running counts in memory,
and periodically flushes them to SQLite as aggregates.

What is recorded: how many times each key was pressed on a given day, how many
clicks/scrolls/pixels of travel, and which application had focus.
What is never recorded: the order keys were pressed in, or any text. The counts
are per-day frequency totals, so the stored data cannot reconstruct what you typed.
"""
from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque
from datetime import datetime

from pynput import keyboard, mouse

from . import config, db, winapi

# Modifier keys, mapped to the label used in shortcut combos.
MODIFIERS = {
    "ctrl": "Ctrl", "ctrl_l": "Ctrl", "ctrl_r": "Ctrl",
    "alt": "Alt", "alt_l": "Alt", "alt_r": "Alt", "alt_gr": "Alt",
    "shift": "Shift", "shift_l": "Shift", "shift_r": "Shift",
    "cmd": "Win", "cmd_l": "Win", "cmd_r": "Win",
}
MODIFIER_ORDER = ("Ctrl", "Alt", "Shift", "Win")

# Keys that erase; used for the "corrections" / accuracy estimate.
CORRECTION_KEYS = {"backspace", "delete"}

KEYSTROKE_MILESTONES = (10_000, 50_000, 100_000, 250_000, 500_000,
                        1_000_000, 2_500_000, 5_000_000, 10_000_000)
CLICK_MILESTONES = (1_000, 5_000, 10_000, 50_000, 100_000,
                    250_000, 500_000, 1_000_000)


def _bucket_key(now: datetime | None = None) -> tuple[str, str]:
    """Return (hour_bucket, day) strings for a moment in time."""
    now = now or datetime.now()
    return now.strftime("%Y-%m-%d %H"), now.strftime("%Y-%m-%d")


def _normalise_key(key) -> str | None:
    """Turn a pynput key into a stable, storable name.

    Letters and digits are stored as the lowercase character; everything else is
    stored by its pynput name ('space', 'backspace', ...). Returns None for keys
    that cannot be identified.
    """
    char = getattr(key, "char", None)
    if char:
        # Ctrl+<letter> arrives as a control character (\x01-\x1a); map it back.
        if len(char) == 1 and ord(char) < 32:
            mapped = chr(ord(char) + 96)
            return mapped if mapped.isalpha() else None
        return char.lower()
    name = getattr(key, "name", None)
    return name.lower() if name else None


class Tracker:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._buckets: dict[str, dict] = defaultdict(lambda: defaultdict(float))
        self._keys: dict[tuple[str, str], int] = defaultdict(int)
        self._apps: dict[tuple[str, str], dict] = defaultdict(lambda: defaultdict(int))
        self._shortcuts: dict[tuple[str, str], int] = defaultdict(int)

        self._held: set = set()          # keys currently down (for auto-repeat suppression)
        self._mods: set[str] = set()     # modifier labels currently down
        self._last_pos: tuple[int, int] | None = None
        self._last_click: tuple[float, int, int] | None = None
        self._stroke_times: deque[float] = deque()

        self._k_listener: keyboard.Listener | None = None
        self._m_listener: mouse.Listener | None = None
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

        settings = config.load()
        self.paused = bool(settings.get("paused"))
        self.started_at = time.time()
        self.new_milestones: list[dict] = []

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        db.init()
        self._k_listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release
        )
        self._m_listener = mouse.Listener(
            on_click=self._on_click, on_scroll=self._on_scroll, on_move=self._on_move
        )
        self._k_listener.daemon = True
        self._m_listener.daemon = True
        self._k_listener.start()
        self._m_listener.start()
        for target in (self._flush_loop, self._heartbeat_loop):
            t = threading.Thread(target=target, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        for listener in (self._k_listener, self._m_listener):
            if listener is not None:
                try:
                    listener.stop()
                except Exception:
                    pass
        self.flush()

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self.paused = bool(paused)
            if paused:
                self._held.clear()
                self._mods.clear()
        config.save({"paused": bool(paused)})
        if paused:
            self.flush()

    # ------------------------------------------------------------ helpers

    def _skip(self) -> str | None:
        """Return the focused app name, or None if this event should be ignored."""
        if self.paused:
            return None
        app = winapi.foreground_app()
        excluded = {a.lower().removesuffix(".exe")
                    for a in config.get("excluded_apps") or []}
        if app and app.lower() in excluded:
            return None
        return app or "unknown"

    def _add(self, field: str, amount: float, app: str | None) -> None:
        bucket, day = _bucket_key()
        with self._lock:
            self._buckets[bucket][field] += amount
            if app and config.get("track_apps") and field in ("keystrokes", "clicks"):
                self._apps[(day, app)][field] += int(amount)

    def _rolling_wpm(self, now: float) -> float:
        """Typing speed over the trailing window, normalised by elapsed time.

        Using the real elapsed span (rather than assuming a full window) keeps
        short bursts honest and lets the reading decay once typing stops.
        """
        window = config.WPM_WINDOW_SECONDS
        strokes = self._stroke_times
        cutoff = now - window
        while strokes and strokes[0] < cutoff:
            strokes.popleft()
        if len(strokes) < 5:
            return 0.0
        span = max(now - strokes[0], 1.0)
        wpm = (len(strokes) / config.CHARS_PER_WORD) / (span / 60.0)
        return round(min(wpm, 300.0), 1)

    # ------------------------------------------------------------ keyboard

    def _on_press(self, key) -> None:
        try:
            app = self._skip()
            if app is None:
                return
            # Ignore OS auto-repeat: the key is already down.
            with self._lock:
                if key in self._held:
                    return
                self._held.add(key)

            name = _normalise_key(key)
            if name is None:
                return

            if name in MODIFIERS:
                with self._lock:
                    self._mods.add(MODIFIERS[name])
                    # Recorded for the keyboard heatmap, but deliberately kept out
                    # of the keystroke total -- a modifier isn't a typed character.
                    if config.get("track_key_detail"):
                        self._keys[(_bucket_key()[1], name)] += 1
                return

            self._add("keystrokes", 1, app)
            bucket, day = _bucket_key()

            with self._lock:
                if config.get("track_key_detail"):
                    self._keys[(day, name)] += 1
                if name in CORRECTION_KEYS:
                    self._buckets[bucket]["backspaces"] += 1
                # Shift alone is capitalisation, not a shortcut.
                mods = [m for m in MODIFIER_ORDER if m in self._mods]
                if mods and set(mods) - {"Shift"}:
                    self._buckets[bucket]["shortcuts"] += 1
                    if config.get("track_shortcuts"):
                        label = "+".join(mods + [name.upper() if len(name) == 1 else name])
                        self._shortcuts[(day, label)] += 1

            now = time.time()
            self._stroke_times.append(now)
            wpm = self._rolling_wpm(now)
            if wpm:
                with self._lock:
                    prev = self._buckets[bucket].get("peak_wpm", 0)
                    self._buckets[bucket]["peak_wpm"] = max(prev, wpm)
        except Exception:
            # A listener callback must never raise -- pynput would tear down the hook.
            pass

    def _on_release(self, key) -> None:
        try:
            with self._lock:
                self._held.discard(key)
                name = _normalise_key(key)
                if name in MODIFIERS:
                    self._mods.discard(MODIFIERS[name])
        except Exception:
            pass

    # ------------------------------------------------------------ mouse

    def _on_click(self, x, y, button, pressed) -> None:
        try:
            if not pressed:
                return
            app = self._skip()
            if app is None:
                return
            name = getattr(button, "name", "left")
            field = {"left": "left_clicks", "right": "right_clicks",
                     "middle": "middle_clicks"}.get(name)
            if field is None:
                return
            self._add("clicks", 1, app)
            self._add(field, 1, None)

            if name == "left":
                now = time.time()
                prev = self._last_click
                if (prev and (now - prev[0]) * 1000 <= config.DOUBLE_CLICK_MS
                        and abs(x - prev[1]) <= config.DOUBLE_CLICK_PX
                        and abs(y - prev[2]) <= config.DOUBLE_CLICK_PX):
                    self._add("double_clicks", 1, None)
                    self._last_click = None  # don't let a triple click count twice
                else:
                    self._last_click = (now, x, y)
        except Exception:
            pass

    def _on_scroll(self, x, y, dx, dy) -> None:
        try:
            app = self._skip()
            if app is None:
                return
            self._add("scrolls", 1, None)
        except Exception:
            pass

    def _on_move(self, x, y) -> None:
        try:
            prev = self._last_pos
            self._last_pos = (x, y)
            if prev is None or self.paused:
                return
            dist = math.hypot(x - prev[0], y - prev[1])
            # Ignore teleports (monitor switches, RDP jumps) and sub-pixel noise.
            if 0.5 < dist < 4000:
                self._add("mouse_px", dist, None)
        except Exception:
            pass

    # ------------------------------------------------------------ background loops

    def _heartbeat_loop(self) -> None:
        """Count a second of 'active time' for every second the user isn't idle."""
        while not self._stop.wait(1.0):
            try:
                if self.paused or winapi.idle_seconds() > config.IDLE_THRESHOLD_SECONDS:
                    continue
                bucket, day = _bucket_key()
                app = winapi.foreground_app() or "unknown"
                excluded = {a.lower().removesuffix(".exe")
                            for a in config.get("excluded_apps") or []}
                if app.lower() in excluded:
                    continue
                with self._lock:
                    self._buckets[bucket]["active_seconds"] += 1
                    if config.get("track_apps"):
                        self._apps[(day, app)]["active_seconds"] += 1
            except Exception:
                pass

    def _flush_loop(self) -> None:
        while not self._stop.wait(config.FLUSH_INTERVAL_SECONDS):
            try:
                self.flush()
            except Exception:
                pass

    def flush(self) -> None:
        """Move buffered counts into the database and check for new milestones."""
        with self._lock:
            if not (self._buckets or self._keys or self._apps or self._shortcuts):
                return
            buckets = {b: dict(v) for b, v in self._buckets.items()}
            keys = dict(self._keys)
            apps = {k: dict(v) for k, v in self._apps.items()}
            shortcuts = dict(self._shortcuts)
            self._buckets.clear()
            self._keys.clear()
            self._apps.clear()
            self._shortcuts.clear()

        # Round accumulated float pixels to a whole number before storing.
        for vals in buckets.values():
            if "mouse_px" in vals:
                vals["mouse_px"] = round(vals["mouse_px"], 2)
            for field in db.HOURLY_COUNTERS:
                if field != "mouse_px" and field in vals:
                    vals[field] = int(vals[field])

        db.flush(buckets, keys, apps, shortcuts)
        self._check_milestones()

    def _check_milestones(self) -> None:
        try:
            start, end = db.range_bounds("all")
            totals = db.totals(start, end)
            for kind, thresholds, value in (
                ("keystrokes", KEYSTROKE_MILESTONES, totals["keystrokes"]),
                ("clicks", CLICK_MILESTONES, totals["clicks"]),
            ):
                for threshold in thresholds:
                    if value >= threshold and db.record_milestone(kind, threshold):
                        self.new_milestones.append({"kind": kind, "threshold": threshold})
        except Exception:
            pass

    # ------------------------------------------------------------ live view

    def live(self) -> dict:
        """Unflushed counters plus today's stored totals, for the dashboard."""
        today = datetime.now().strftime("%Y-%m-%d")
        stored = db.totals(today, today)
        with self._lock:
            pending_keys = sum(int(v.get("keystrokes", 0)) for v in self._buckets.values())
            pending_clicks = sum(int(v.get("clicks", 0)) for v in self._buckets.values())
            pending_scrolls = sum(int(v.get("scrolls", 0)) for v in self._buckets.values())
            pending_px = sum(v.get("mouse_px", 0) for v in self._buckets.values())
            pending_active = sum(int(v.get("active_seconds", 0)) for v in self._buckets.values())
        return {
            "keystrokes": stored["keystrokes"] + pending_keys,
            "clicks": stored["clicks"] + pending_clicks,
            "scrolls": stored["scrolls"] + pending_scrolls,
            "mouse_px": stored["mouse_px"] + pending_px,
            "active_seconds": stored["active_seconds"] + pending_active,
            "wpm": self._rolling_wpm(time.time()),
            "paused": self.paused,
            "idle_seconds": round(winapi.idle_seconds(), 1),
            "uptime_seconds": round(time.time() - self.started_at),
        }


_tracker: Tracker | None = None


def get_tracker() -> Tracker:
    """Return the process-wide tracker, creating it on first call."""
    global _tracker
    if _tracker is None:
        _tracker = Tracker()
    return _tracker
