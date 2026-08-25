"""Behaviour tests for the tracker's counting logic.

Runs against a throwaway database in a temp directory, and feeds synthetic
pynput events straight into the listener callbacks -- no real input required.

    python tests\\test_tracker.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["KEYTRENDS_DATA_DIR"] = tempfile.mkdtemp(prefix="keytrends-test-")

from pynput import keyboard, mouse  # noqa: E402

from keytrends import db, tracker, winapi  # noqa: E402

# Pin the focused app so results don't depend on what's on screen.
winapi.foreground_app = lambda: "testapp"
winapi.idle_seconds = lambda: 0.0

K = keyboard.KeyCode.from_char
checks: list[tuple[str, object, object]] = []


def check(label, got, want):
    checks.append((label, got, want))


def main() -> int:
    db.init()
    db.purge_all()
    t = tracker.Tracker()

    # Plain typing.
    for ch in "hello world":
        key = K(ch) if ch != " " else keyboard.Key.space
        t._on_press(key)
        t._on_release(key)

    # Held key: the OS repeats it, but it should count once.
    rep = K("z")
    for _ in range(5):
        t._on_press(rep)
    t._on_release(rep)

    # A real shortcut.
    t._on_press(keyboard.Key.ctrl_l)
    t._on_press(K("s"))
    t._on_release(K("s"))
    t._on_release(keyboard.Key.ctrl_l)

    # Shift+A is capitalisation, not a shortcut.
    t._on_press(keyboard.Key.shift)
    t._on_press(K("a"))
    t._on_release(K("a"))
    t._on_release(keyboard.Key.shift)

    # Corrections.
    for _ in range(3):
        t._on_press(keyboard.Key.backspace)
        t._on_release(keyboard.Key.backspace)

    # Clicks, including a double click and an ignored release.
    t._on_click(10, 10, mouse.Button.left, True)
    t._on_click(11, 10, mouse.Button.left, True)
    t._on_click(500, 500, mouse.Button.right, True)
    t._on_click(300, 300, mouse.Button.middle, True)
    t._on_click(10, 10, mouse.Button.left, False)

    # Scrolling and movement, including a teleport that must be ignored.
    t._on_scroll(0, 0, 0, -1)
    t._on_scroll(0, 0, 0, -1)
    t._on_move(0, 0)
    t._on_move(3, 4)        # 5 px
    t._on_move(3, 104)      # 100 px
    t._on_move(99999, 104)  # monitor jump -- ignored

    t.flush()

    start, end = db.range_bounds("today")
    tot = db.totals(start, end)
    keys = {r["key"]: r["count"] for r in db.key_counts(start, end)}
    combos = {r["combo"]: r["count"] for r in db.shortcut_counts(start, end)}
    apps = db.app_usage(start, end)

    expected = len("hello world") + 1 + 1 + 1 + 3  # text + z + s + a + 3 backspaces

    check("keystroke total", tot["keystrokes"], expected)
    check("auto-repeat counted once", keys.get("z"), 1)
    check("repeated letter counted per press", keys.get("l"), 3)
    check("space counted", keys.get("space"), 1)
    check("modifier kept out of total", tot["keystrokes"], expected)
    check("modifier recorded for heatmap", keys.get("ctrl_l"), 1)
    check("corrections", tot["backspaces"], 3)
    check("shortcut count", tot["shortcuts"], 1)
    check("Ctrl+S recorded", combos.get("Ctrl+S"), 1)
    check("Shift+A not a shortcut", combos.get("Shift+A"), None)
    check("clicks", tot["clicks"], 4)
    check("left clicks", tot["left_clicks"], 2)
    check("right clicks", tot["right_clicks"], 1)
    check("middle clicks", tot["middle_clicks"], 1)
    check("double click detected", tot["double_clicks"], 1)
    check("scrolls", tot["scrolls"], 2)
    check("cursor distance ignores teleport", round(tot["mouse_px"]), 105)
    check("app attributed", apps[0]["app"] if apps else None, "testapp")
    check("app keystrokes", apps[0]["keystrokes"] if apps else None, expected)

    # live() must include counts that haven't been flushed yet.
    t._on_press(K("q"))
    t._on_release(K("q"))
    check("live includes unflushed", t.live()["keystrokes"], expected + 1)

    # Pausing must drop input entirely.
    t.set_paused(True)
    before = t.live()["keystrokes"]
    t._on_press(K("w"))
    t._on_release(K("w"))
    t.flush()
    check("paused ignores input", t.live()["keystrokes"], before)

    failures = 0
    for label, got, want in checks:
        ok = got == want
        failures += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {label}: got {got!r}, want {want!r}")

    print(f"\n{len(checks) - failures}/{len(checks)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
