"""Derived metrics and the plain-language insights shown on the dashboard."""
from __future__ import annotations

from datetime import datetime, timedelta

from . import db

DOW_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

# Assume a typical 96-DPI display when converting pixels of travel to real distance.
_PX_PER_INCH = 96.0
_METRES_PER_INCH = 0.0254

# Friendly key labels for the "top keys" list.
KEY_LABELS = {
    "space": "Space", "backspace": "Backspace", "enter": "Enter", "tab": "Tab",
    "esc": "Esc", "delete": "Delete", "shift": "Shift", "ctrl_l": "Ctrl",
    "ctrl_r": "Ctrl", "alt_l": "Alt", "alt_gr": "AltGr", "up": "Up", "down": "Down",
    "left": "Left", "right": "Right", "caps_lock": "Caps", "home": "Home",
    "end": "End", "page_up": "PgUp", "page_down": "PgDn",
}


def px_to_metres(px: float) -> float:
    return px * _METRES_PER_INCH / _PX_PER_INCH


def key_label(name: str) -> str:
    if name in KEY_LABELS:
        return KEY_LABELS[name]
    if len(name) == 1:
        return name.upper() if name.isalpha() else name
    return name.replace("_", " ").title()


def format_duration(seconds: float) -> str:
    seconds = int(seconds or 0)
    hours, rem = divmod(seconds, 3600)
    minutes = rem // 60
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m"
    return f"{seconds}s"


def _pct_change(current: float, previous: float) -> float | None:
    if not previous:
        return None
    return round((current - previous) / previous * 100, 1)


def _previous_bounds(start: str, end: str) -> tuple[str, str]:
    """The equally long window immediately before [start, end]."""
    s = datetime.strptime(start, "%Y-%m-%d").date()
    e = datetime.strptime(end, "%Y-%m-%d").date()
    span = (e - s).days + 1
    return (s - timedelta(days=span)).isoformat(), (s - timedelta(days=1)).isoformat()


def summary(start: str, end: str) -> dict:
    """Headline numbers for a range, with change vs the preceding window."""
    tot = db.totals(start, end)
    prev = db.totals(*_previous_bounds(start, end))
    days = max(tot.get("days") or 0, 1)
    active_seconds = tot["active_seconds"] or 0
    active_minutes = active_seconds / 60.0

    keystrokes = tot["keystrokes"]
    clicks = tot["clicks"]
    total_input = keystrokes + clicks

    return {
        "keystrokes": keystrokes,
        "clicks": clicks,
        "scrolls": tot["scrolls"],
        "left_clicks": tot["left_clicks"],
        "right_clicks": tot["right_clicks"],
        "middle_clicks": tot["middle_clicks"],
        "double_clicks": tot["double_clicks"],
        "backspaces": tot["backspaces"],
        "shortcuts": tot["shortcuts"],
        "peak_wpm": round(tot["peak_wpm"] or 0, 1),
        "active_seconds": active_seconds,
        "active_label": format_duration(active_seconds),
        "days_tracked": tot.get("days") or 0,
        "mouse_px": round(tot["mouse_px"] or 0),
        "mouse_metres": round(px_to_metres(tot["mouse_px"] or 0), 1),
        "words": round(keystrokes / 5),
        "avg_keystrokes_per_day": round(keystrokes / days),
        "avg_clicks_per_day": round(clicks / days),
        "avg_active_per_day": format_duration(active_seconds / days),
        "keys_per_minute": round(keystrokes / active_minutes, 1) if active_minutes else 0,
        "clicks_per_minute": round(clicks / active_minutes, 1) if active_minutes else 0,
        # Share of all input events that were keystrokes -- the keyboard/mouse balance.
        "keyboard_share": round(keystrokes / total_input * 100, 1) if total_input else 0,
        "correction_rate": round(tot["backspaces"] / keystrokes * 100, 1) if keystrokes else 0,
        "shortcut_rate": round(tot["shortcuts"] / keystrokes * 1000, 1) if keystrokes else 0,
        "change": {
            "keystrokes": _pct_change(keystrokes, prev["keystrokes"]),
            "clicks": _pct_change(clicks, prev["clicks"]),
            "active_seconds": _pct_change(active_seconds, prev["active_seconds"] or 0),
        },
    }


def _distance_comparison(metres: float) -> str | None:
    """A human-scale reference point for how far the mouse travelled."""
    references = [
        (42195, "marathon"),
        (10000, "10K run"),
        (1609, "mile"),
        (400, "running track lap"),
        (105, "football pitch"),
    ]
    for size, name in references:
        if metres >= size:
            times = metres / size
            if times >= 1.5:
                return f"about {times:.1f} {name}s"
            return f"about the length of a {name}"
    return None


def build(start: str, end: str, rng_label: str) -> list[dict]:
    """Generate the ranked list of narrative insights for a range."""
    out: list[dict] = []
    s = summary(start, end)
    if not (s["keystrokes"] or s["clicks"]):
        return [{
            "title": "No activity recorded yet",
            "detail": "Once tracking has been running for a while, your trends will appear here.",
            "kind": "empty",
        }]

    # --- Trend vs the previous window
    change = s["change"]["keystrokes"]
    if change is not None and abs(change) >= 5:
        direction = "up" if change > 0 else "down"
        out.append({
            "title": f"Typing is {direction} {abs(change):.0f}%",
            "detail": (f"You typed {s['keystrokes']:,} keys this period, "
                       f"{direction} {abs(change):.0f}% from the previous {rng_label}."),
            "kind": "trend",
            "direction": direction,
        })

    # --- Peak hour
    hourly = db.hourly_profile(start, end)
    busiest = max(hourly, key=lambda h: h["keystrokes"] + h["clicks"])
    if busiest["keystrokes"] + busiest["clicks"] > 0:
        total = sum(h["keystrokes"] + h["clicks"] for h in hourly) or 1
        share = (busiest["keystrokes"] + busiest["clicks"]) / total * 100
        hour = busiest["hour"]
        out.append({
            "title": f"Peak hour is {_hour_label(hour)}",
            "detail": (f"{share:.0f}% of your input happens in the {_hour_label(hour)} hour. "
                       f"{_chronotype(hour)}"),
            "kind": "time",
        })

    # --- Weekday pattern
    dows = db.dow_totals(start, end)
    active = [d for d in dows if d["avg_keystrokes"] > 0]
    if len(active) >= 3:
        top = max(active, key=lambda d: d["avg_keystrokes"])
        low = min(active, key=lambda d: d["avg_keystrokes"])
        if top["dow"] != low["dow"] and low["avg_keystrokes"]:
            ratio = top["avg_keystrokes"] / low["avg_keystrokes"]
            out.append({
                "title": f"{DOW_NAMES[top['dow']]} is your busiest day",
                "detail": (f"You average {top['avg_keystrokes']:,} keystrokes on "
                           f"{DOW_NAMES[top['dow']]}s — {ratio:.1f}x your "
                           f"{DOW_NAMES[low['dow']]} average."),
                "kind": "time",
            })

    # --- Keyboard vs mouse balance
    if s["keyboard_share"]:
        share = s["keyboard_share"]
        if share >= 80:
            verdict = "You're strongly keyboard-driven."
        elif share >= 60:
            verdict = "You lean on the keyboard more than the mouse."
        elif share >= 40:
            verdict = "You split your input fairly evenly."
        else:
            verdict = "You're a mouse-first user."
        out.append({
            "title": f"{share:.0f}% keyboard, {100 - share:.0f}% mouse",
            "detail": f"{verdict} That's {s['keystrokes']:,} keystrokes against {s['clicks']:,} clicks.",
            "kind": "balance",
        })

    # --- Correction rate
    if s["keystrokes"] > 500:
        rate = s["correction_rate"]
        if rate >= 12:
            note = "That's on the high side — slowing down slightly often costs less time than the fixes."
        elif rate >= 6:
            note = "That's a typical rate for everyday typing."
        else:
            note = "That's a notably clean rate."
        out.append({
            "title": f"{rate:.1f}% of keys were corrections",
            "detail": f"You pressed Backspace or Delete {s['backspaces']:,} times. {note}",
            "kind": "accuracy",
        })

    # --- Shortcut usage
    if s["keystrokes"] > 500:
        rate = s["shortcut_rate"]
        top_shortcuts = db.shortcut_counts(start, end, limit=1)
        favourite = top_shortcuts[0]["combo"] if top_shortcuts else None
        if rate >= 25:
            verdict = "You're a heavy shortcut user."
        elif rate >= 8:
            verdict = "You use shortcuts regularly."
        else:
            verdict = "There's room to lean on shortcuts more."
        detail = f"{verdict} That's {rate:.0f} shortcuts per 1,000 keystrokes."
        if favourite:
            detail += f" Your most used is {favourite}."
        out.append({"title": f"{s['shortcuts']:,} shortcuts used", "detail": detail,
                    "kind": "shortcuts"})

    # --- Mouse travel
    if s["mouse_metres"] >= 1:
        metres = s["mouse_metres"]
        distance = f"{metres / 1000:.2f} km" if metres >= 1000 else f"{metres:.0f} m"
        comparison = _distance_comparison(metres)
        detail = f"Your cursor covered {distance} across the screen."
        if comparison:
            detail += f" That's {comparison}."
        out.append({"title": f"Mouse travelled {distance}", "detail": detail, "kind": "mouse"})

    # --- Top application
    apps = db.app_usage(start, end, limit=3)
    if apps:
        total_events = sum(a["keystrokes"] + a["clicks"] for a in apps) or 1
        top = apps[0]
        share = (top["keystrokes"] + top["clicks"]) / total_events * 100
        out.append({
            "title": f"{top['app']} takes the most input",
            "detail": (f"{share:.0f}% of your tracked input went to {top['app']}, "
                       f"with {format_duration(top['active_seconds'])} of active time."),
            "kind": "apps",
        })

    # --- Most used key
    keys = db.key_counts(start, end, limit=5)
    letters = [k for k in keys if len(k["key"]) == 1 and k["key"].isalpha()]
    if letters:
        top = letters[0]
        total_keys = sum(k["count"] for k in db.key_counts(start, end)) or 1
        out.append({
            "title": f"'{top['key'].upper()}' is your most-pressed letter",
            "detail": (f"Pressed {top['count']:,} times — "
                       f"{top['count'] / total_keys * 100:.1f}% of all keys."),
            "kind": "keys",
        })

    # --- Typing speed
    if s["peak_wpm"]:
        out.append({
            "title": f"Peak speed {s['peak_wpm']:.0f} WPM",
            "detail": (f"Across all active time — reading and thinking included — you "
                       f"average {s['keys_per_minute']:.0f} keys a minute, or roughly "
                       f"{s['words']:,} words typed in total."),
            "kind": "speed",
        })

    # --- Streaks
    st = db.streaks()
    if st["current"] >= 2:
        out.append({
            "title": f"{st['current']}-day tracking streak",
            "detail": (f"Your longest streak is {st['longest']} days across "
                       f"{st['total_active_days']} tracked days in total."),
            "kind": "streak",
        })

    return out


def _hour_label(hour: int) -> str:
    if hour == 0:
        return "12 AM"
    if hour < 12:
        return f"{hour} AM"
    if hour == 12:
        return "12 PM"
    return f"{hour - 12} PM"


def _chronotype(hour: int) -> str:
    if hour < 6:
        return "That makes you a night owl."
    if hour < 12:
        return "You're a morning worker."
    if hour < 17:
        return "You peak in the afternoon."
    if hour < 21:
        return "You peak in the evening."
    return "That makes you a night owl."
