"""Fill a demo database with ~90 days of plausible activity.

Useful for seeing what the dashboard looks like without waiting three months,
and for the screenshots in the README. It writes to a separate data directory,
so your real statistics are never touched.

    python tools\\seed_demo.py
    python tools\\seed_demo.py --serve      # seed, then open the dashboard

The data is synthetic: a work-shaped daily curve, English letter frequencies,
and a handful of typical applications.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import webbrowser
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEMO_DIR = ROOT / "demo-data"
DEMO_PORT = 8732

# Relative English letter frequency.
LETTERS = {
    "e": 12.7, "t": 9.1, "a": 8.2, "o": 7.5, "i": 7.0, "n": 6.7, "s": 6.3, "h": 6.1,
    "r": 6.0, "d": 4.3, "l": 4.0, "c": 2.8, "u": 2.8, "m": 2.4, "w": 2.4, "f": 2.2,
    "g": 2.0, "y": 2.0, "p": 1.9, "b": 1.5, "v": 1.0, "k": 0.8, "j": 0.15,
    "x": 0.15, "q": 0.10, "z": 0.07,
}
# The non-letter keys a real session produces, at roughly realistic rates.
OTHER = {
    "space": 18.0, "backspace": 6.0, "enter": 3.0, "shift_l": 5.0, "shift_r": 1.2,
    "ctrl_l": 3.0, "alt_l": 0.8, "tab": 1.5, ".": 1.6, ",": 1.4, "'": 0.6,
    ";": 0.5, "/": 0.5, "-": 0.5, "=": 0.2, "[": 0.2, "]": 0.2, "up": 0.9,
    "down": 0.9, "left": 0.7, "right": 0.7, "delete": 0.6, "esc": 0.5,
    "caps_lock": 0.1, "cmd": 0.4, "f5": 0.2, "f12": 0.1, "1": 0.9, "2": 0.8,
    "3": 0.7, "4": 0.6, "5": 0.5, "6": 0.4, "7": 0.4, "8": 0.4, "9": 0.4,
    "0": 0.5, "`": 0.2, "\\": 0.15,
}
APPS = [("chrome", 0.30), ("Code", 0.34), ("slack", 0.12), ("WindowsTerminal", 0.10),
        ("EXCEL", 0.07), ("Spotify", 0.04), ("explorer", 0.03)]
SHORTCUTS = [("Ctrl+C", 0.20), ("Ctrl+V", 0.19), ("Ctrl+S", 0.14), ("Ctrl+Z", 0.10),
             ("Alt+Tab", 0.10), ("Ctrl+T", 0.06), ("Ctrl+W", 0.06), ("Ctrl+F", 0.05),
             ("Ctrl+Shift+T", 0.04), ("Win+L", 0.03), ("Ctrl+Shift+P", 0.03)]

# Typing volume by hour: a work day with a post-lunch dip and an evening tail.
HOUR_WEIGHT = [0.02, 0.01, 0.0, 0.0, 0.0, 0.0, 0.05, 0.20, 0.55, 0.95, 1.00, 0.90,
               0.45, 0.70, 0.95, 1.00, 0.85, 0.60, 0.35, 0.40, 0.45, 0.35, 0.18, 0.06]


def seed(days: int = 90, seed_value: int = 7) -> None:
    from keytrends import db

    random.seed(seed_value)
    db.init()
    db.purge_all()

    today = date.today()
    buckets: dict[str, dict] = {}
    keys: dict[tuple[str, str], int] = {}
    apps: dict[tuple[str, str], dict] = {}
    shortcuts: dict[tuple[str, str], int] = {}

    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        iso = day.isoformat()
        dow = day.weekday()
        if dow >= 5 and random.random() < 0.45:
            continue                       # plenty of weekends are simply idle
        weekend = 0.28 if dow >= 5 else 1.0
        trend = 0.75 + 0.5 * (days - 1 - offset) / (days - 1)
        day_scale = weekend * trend * random.uniform(0.7, 1.3)

        for hour in range(24):
            weight = HOUR_WEIGHT[hour] * day_scale
            if weight < 0.02 or random.random() > min(0.97, weight + 0.12):
                continue
            strokes = int(random.gauss(900, 260) * weight)
            if strokes <= 0:
                continue
            clicks = max(0, int(strokes * random.uniform(0.10, 0.24)))
            left = int(clicks * random.uniform(0.72, 0.84))
            right = int(clicks * random.uniform(0.05, 0.11))
            active = min(3600, int(random.uniform(1500, 3300) * min(1.0, weight)))
            combos = int(strokes * random.uniform(0.010, 0.030))

            buckets[f"{iso} {hour:02d}"] = {
                "keystrokes": strokes,
                "clicks": clicks,
                "left_clicks": left,
                "right_clicks": right,
                "middle_clicks": max(0, clicks - left - right),
                "double_clicks": int(left * random.uniform(0.05, 0.13)),
                "scrolls": max(0, int(clicks * random.uniform(0.5, 1.6))),
                "mouse_px": round(clicks * random.uniform(900, 2200), 2),
                "active_seconds": active,
                "backspaces": int(strokes * random.uniform(0.05, 0.10)),
                "shortcuts": combos,
                "peak_wpm": round(random.uniform(52, 96), 1),
            }

            pool = {**LETTERS, **OTHER}
            total_weight = sum(pool.values())
            for name, w in pool.items():
                n = int(strokes * (w / total_weight) * random.uniform(0.85, 1.15))
                if n:
                    keys[(iso, name)] = keys.get((iso, name), 0) + n

            for app, share in APPS:
                k = int(strokes * share * random.uniform(0.8, 1.2))
                c = int(clicks * share * random.uniform(0.8, 1.2))
                if k or c:
                    entry = apps.setdefault((iso, app),
                                            {"keystrokes": 0, "clicks": 0, "active_seconds": 0})
                    entry["keystrokes"] += k
                    entry["clicks"] += c
                    entry["active_seconds"] += int(active * share)

            for combo, share in SHORTCUTS:
                n = int(combos * share * random.uniform(0.7, 1.3))
                if n:
                    shortcuts[(iso, combo)] = shortcuts.get((iso, combo), 0) + n

    db.flush(buckets, keys, apps, shortcuts)

    start, end = db.range_bounds("all")
    totals = db.totals(start, end)
    for kind, thresholds in (
        ("keystrokes", (10_000, 50_000, 100_000, 250_000, 500_000, 1_000_000)),
        ("clicks", (1_000, 5_000, 10_000, 50_000, 100_000)),
    ):
        for threshold in thresholds:
            if totals[kind] >= threshold:
                db.record_milestone(kind, threshold)

    print(f"Demo data written to {DEMO_DIR}")
    print(f"  days with activity : {totals['days']}")
    print(f"  keystrokes         : {totals['keystrokes']:,}")
    print(f"  clicks             : {totals['clicks']:,}")
    print(f"  active time        : {totals['active_seconds'] // 3600}h")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=90, help="how many days to generate")
    parser.add_argument("--seed", type=int, default=7, help="random seed")
    parser.add_argument("--serve", action="store_true",
                        help="start the dashboard on the demo data afterwards")
    args = parser.parse_args()

    # Point KeyTrends at the demo directory before importing anything that reads it.
    os.environ["KEYTRENDS_DATA_DIR"] = str(DEMO_DIR)
    seed(days=args.days, seed_value=args.seed)

    if args.serve:
        from keytrends import server
        url = f"http://127.0.0.1:{DEMO_PORT}/"
        print(f"\nDemo dashboard: {url}  (Ctrl+C to stop)")
        webbrowser.open(url)
        server.run(host="127.0.0.1", port=DEMO_PORT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
