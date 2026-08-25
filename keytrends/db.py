"""SQLite storage for KeyTrends.

Everything here is an *aggregate*: per-hour totals and per-day frequency counts.
Keystroke order is never written to disk, so the database cannot reconstruct
anything that was typed.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import date, datetime, timedelta

from . import config

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS hourly (
    bucket         TEXT PRIMARY KEY,   -- 'YYYY-MM-DD HH'
    day            TEXT NOT NULL,
    hour           INTEGER NOT NULL,
    dow            INTEGER NOT NULL,   -- 0 = Monday
    keystrokes     INTEGER NOT NULL DEFAULT 0,
    clicks         INTEGER NOT NULL DEFAULT 0,
    left_clicks    INTEGER NOT NULL DEFAULT 0,
    right_clicks   INTEGER NOT NULL DEFAULT 0,
    middle_clicks  INTEGER NOT NULL DEFAULT 0,
    double_clicks  INTEGER NOT NULL DEFAULT 0,
    scrolls        INTEGER NOT NULL DEFAULT 0,
    mouse_px       REAL    NOT NULL DEFAULT 0,
    active_seconds INTEGER NOT NULL DEFAULT 0,
    backspaces     INTEGER NOT NULL DEFAULT 0,
    shortcuts      INTEGER NOT NULL DEFAULT 0,
    peak_wpm       REAL    NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_hourly_day ON hourly(day);

CREATE TABLE IF NOT EXISTS key_counts (
    day   TEXT NOT NULL,
    key   TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, key)
);

CREATE TABLE IF NOT EXISTS shortcut_counts (
    day   TEXT NOT NULL,
    combo TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, combo)
);

CREATE TABLE IF NOT EXISTS app_usage (
    day            TEXT NOT NULL,
    app            TEXT NOT NULL,
    keystrokes     INTEGER NOT NULL DEFAULT 0,
    clicks         INTEGER NOT NULL DEFAULT 0,
    active_seconds INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, app)
);

CREATE TABLE IF NOT EXISTS milestones (
    kind        TEXT NOT NULL,
    threshold   INTEGER NOT NULL,
    achieved_at TEXT NOT NULL,
    PRIMARY KEY (kind, threshold)
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect() -> sqlite3.Connection:
    """Return this thread's connection, creating the schema on first use."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(config.DB_PATH, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(SCHEMA)
        conn.commit()
        _local.conn = conn
    return conn


def init() -> None:
    conn = connect()
    row = conn.execute("SELECT value FROM meta WHERE key='first_run'").fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('first_run', ?)",
            (datetime.now().isoformat(timespec="seconds"),),
        )
        conn.commit()


def first_run() -> str | None:
    row = connect().execute("SELECT value FROM meta WHERE key='first_run'").fetchone()
    return row["value"] if row else None


# ---------------------------------------------------------------- writes

HOURLY_COUNTERS = (
    "keystrokes", "clicks", "left_clicks", "right_clicks", "middle_clicks",
    "double_clicks", "scrolls", "mouse_px", "active_seconds", "backspaces",
    "shortcuts",
)


def flush(buckets: dict, keys: dict, apps: dict, shortcuts: dict) -> None:
    """Add a batch of buffered counts to the stored aggregates.

    `buckets` maps 'YYYY-MM-DD HH' to a dict of counter deltas (plus an optional
    `peak_wpm`, which is kept as a maximum rather than summed).
    """
    conn = connect()
    with conn:
        for bucket, vals in buckets.items():
            day, hour = bucket.split(" ")
            dow = datetime.strptime(day, "%Y-%m-%d").weekday()
            conn.execute(
                "INSERT OR IGNORE INTO hourly(bucket, day, hour, dow) VALUES (?,?,?,?)",
                (bucket, day, int(hour), dow),
            )
            sets, params = [], []
            for name in HOURLY_COUNTERS:
                delta = vals.get(name)
                if delta:
                    sets.append(name + " = " + name + " + ?")
                    params.append(delta)
            if vals.get("peak_wpm"):
                sets.append("peak_wpm = MAX(peak_wpm, ?)")
                params.append(vals["peak_wpm"])
            if sets:
                params.append(bucket)
                conn.execute(
                    "UPDATE hourly SET " + ", ".join(sets) + " WHERE bucket = ?", params
                )

        for (day, key), count in keys.items():
            conn.execute(
                "INSERT INTO key_counts(day, key, count) VALUES (?,?,?) "
                "ON CONFLICT(day, key) DO UPDATE SET count = count + excluded.count",
                (day, key, count),
            )
        for (day, combo), count in shortcuts.items():
            conn.execute(
                "INSERT INTO shortcut_counts(day, combo, count) VALUES (?,?,?) "
                "ON CONFLICT(day, combo) DO UPDATE SET count = count + excluded.count",
                (day, combo, count),
            )
        for (day, app), vals in apps.items():
            conn.execute("INSERT OR IGNORE INTO app_usage(day, app) VALUES (?,?)", (day, app))
            conn.execute(
                "UPDATE app_usage SET keystrokes = keystrokes + ?, clicks = clicks + ?, "
                "active_seconds = active_seconds + ? WHERE day = ? AND app = ?",
                (vals.get("keystrokes", 0), vals.get("clicks", 0),
                 vals.get("active_seconds", 0), day, app),
            )


# ---------------------------------------------------------------- range helper

RANGES = {"today": 1, "7d": 7, "30d": 30, "90d": 90, "365d": 365, "all": None}


def range_bounds(rng: str) -> tuple[str, str]:
    """Return inclusive (start_day, end_day) strings for a named range."""
    today = date.today()
    days = RANGES.get(rng, 30)
    if days is None:
        row = connect().execute("SELECT MIN(day) AS d FROM hourly").fetchone()
        start = row["d"] if row and row["d"] else today.isoformat()
    else:
        start = (today - timedelta(days=days - 1)).isoformat()
    return start, today.isoformat()


# ---------------------------------------------------------------- reads

def totals(start: str, end: str) -> dict:
    row = connect().execute(
        """SELECT COALESCE(SUM(keystrokes),0)     AS keystrokes,
                  COALESCE(SUM(clicks),0)         AS clicks,
                  COALESCE(SUM(left_clicks),0)    AS left_clicks,
                  COALESCE(SUM(right_clicks),0)   AS right_clicks,
                  COALESCE(SUM(middle_clicks),0)  AS middle_clicks,
                  COALESCE(SUM(double_clicks),0)  AS double_clicks,
                  COALESCE(SUM(scrolls),0)        AS scrolls,
                  COALESCE(SUM(mouse_px),0)       AS mouse_px,
                  COALESCE(SUM(active_seconds),0) AS active_seconds,
                  COALESCE(SUM(backspaces),0)     AS backspaces,
                  COALESCE(SUM(shortcuts),0)      AS shortcuts,
                  COALESCE(MAX(peak_wpm),0)       AS peak_wpm,
                  COUNT(DISTINCT day)             AS days
           FROM hourly WHERE day BETWEEN ? AND ?""",
        (start, end),
    ).fetchone()
    return dict(row)


def daily_series(start: str, end: str) -> list[dict]:
    """One row per calendar day in the range, including days with no activity."""
    rows = {
        r["day"]: dict(r)
        for r in connect().execute(
            """SELECT day,
                      SUM(keystrokes)     AS keystrokes,
                      SUM(clicks)         AS clicks,
                      SUM(scrolls)        AS scrolls,
                      SUM(mouse_px)       AS mouse_px,
                      SUM(active_seconds) AS active_seconds,
                      MAX(peak_wpm)       AS peak_wpm
               FROM hourly WHERE day BETWEEN ? AND ?
               GROUP BY day ORDER BY day""",
            (start, end),
        ).fetchall()
    }
    out = []
    cur = datetime.strptime(start, "%Y-%m-%d").date()
    last = datetime.strptime(end, "%Y-%m-%d").date()
    while cur <= last:
        key = cur.isoformat()
        out.append(rows.get(key) or {
            "day": key, "keystrokes": 0, "clicks": 0, "scrolls": 0,
            "mouse_px": 0, "active_seconds": 0, "peak_wpm": 0,
        })
        cur += timedelta(days=1)
    return out


def hourly_profile(start: str, end: str) -> list[dict]:
    """Totals per hour-of-day (0-23), summed across the range."""
    rows = {
        r["hour"]: dict(r)
        for r in connect().execute(
            """SELECT hour, SUM(keystrokes) AS keystrokes, SUM(clicks) AS clicks
               FROM hourly WHERE day BETWEEN ? AND ? GROUP BY hour""",
            (start, end),
        ).fetchall()
    }
    return [rows.get(h) or {"hour": h, "keystrokes": 0, "clicks": 0} for h in range(24)]


def dow_hour_matrix(start: str, end: str) -> list[list[int]]:
    """7x24 grid of keystrokes+clicks, indexed [day_of_week][hour]."""
    grid = [[0] * 24 for _ in range(7)]
    for r in connect().execute(
        """SELECT dow, hour, SUM(keystrokes + clicks) AS total
           FROM hourly WHERE day BETWEEN ? AND ? GROUP BY dow, hour""",
        (start, end),
    ):
        grid[r["dow"]][r["hour"]] = r["total"] or 0
    return grid


def key_counts(start: str, end: str, limit: int | None = None) -> list[dict]:
    sql = ("SELECT key, SUM(count) AS count FROM key_counts "
           "WHERE day BETWEEN ? AND ? GROUP BY key ORDER BY count DESC")
    params: list = [start, end]
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return [dict(r) for r in connect().execute(sql, params)]


def shortcut_counts(start: str, end: str, limit: int = 12) -> list[dict]:
    return [dict(r) for r in connect().execute(
        "SELECT combo, SUM(count) AS count FROM shortcut_counts "
        "WHERE day BETWEEN ? AND ? GROUP BY combo ORDER BY count DESC LIMIT ?",
        (start, end, limit),
    )]


def app_usage(start: str, end: str, limit: int = 10) -> list[dict]:
    return [dict(r) for r in connect().execute(
        """SELECT app, SUM(keystrokes) AS keystrokes, SUM(clicks) AS clicks,
                  SUM(active_seconds) AS active_seconds
           FROM app_usage WHERE day BETWEEN ? AND ?
           GROUP BY app ORDER BY (SUM(keystrokes) + SUM(clicks)) DESC LIMIT ?""",
        (start, end, limit),
    )]


def dow_totals(start: str, end: str) -> list[dict]:
    """Average activity per weekday, normalised by how many of each weekday occurred."""
    rows = {
        r["dow"]: dict(r)
        for r in connect().execute(
            """SELECT dow, SUM(keystrokes) AS keystrokes, SUM(clicks) AS clicks,
                      COUNT(DISTINCT day) AS days
               FROM hourly WHERE day BETWEEN ? AND ? GROUP BY dow""",
            (start, end),
        )
    }
    out = []
    for d in range(7):
        r = rows.get(d) or {"dow": d, "keystrokes": 0, "clicks": 0, "days": 0}
        days = r["days"] or 1
        out.append({
            "dow": d,
            "keystrokes": r["keystrokes"] or 0,
            "clicks": r["clicks"] or 0,
            "avg_keystrokes": round((r["keystrokes"] or 0) / days),
            "avg_clicks": round((r["clicks"] or 0) / days),
        })
    return out


def records() -> dict:
    conn = connect()
    best_day = conn.execute(
        "SELECT day, SUM(keystrokes) AS keystrokes, SUM(clicks) AS clicks "
        "FROM hourly GROUP BY day ORDER BY (SUM(keystrokes)+SUM(clicks)) DESC LIMIT 1"
    ).fetchone()
    best_hour = conn.execute(
        "SELECT bucket, keystrokes, clicks FROM hourly "
        "ORDER BY (keystrokes + clicks) DESC LIMIT 1"
    ).fetchone()
    peak = conn.execute("SELECT MAX(peak_wpm) AS wpm FROM hourly").fetchone()
    return {
        "best_day": dict(best_day) if best_day else None,
        "best_hour": dict(best_hour) if best_hour else None,
        "peak_wpm": round((peak["wpm"] or 0) if peak else 0, 1),
    }


def active_days() -> list[str]:
    """Every day with recorded activity, oldest first."""
    return [r["day"] for r in connect().execute(
        "SELECT day FROM hourly GROUP BY day HAVING SUM(keystrokes + clicks) > 0 ORDER BY day"
    )]


def streaks() -> dict:
    """Current and longest run of consecutive active days."""
    days = [datetime.strptime(d, "%Y-%m-%d").date() for d in active_days()]
    if not days:
        return {"current": 0, "longest": 0, "total_active_days": 0}
    longest = run = 1
    for prev, cur in zip(days, days[1:]):
        run = run + 1 if (cur - prev).days == 1 else 1
        longest = max(longest, run)
    today = date.today()
    current = 0
    # A streak only counts as "current" if it reaches today or yesterday.
    if days[-1] in (today, today - timedelta(days=1)):
        current = 1
        for i in range(len(days) - 1, 0, -1):
            if (days[i] - days[i - 1]).days == 1:
                current += 1
            else:
                break
    return {"current": current, "longest": longest, "total_active_days": len(days)}


def record_milestone(kind: str, threshold: int) -> bool:
    """Store a newly reached milestone. Returns True if it was not already stored."""
    conn = connect()
    with conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO milestones(kind, threshold, achieved_at) VALUES (?,?,?)",
            (kind, threshold, datetime.now().isoformat(timespec="seconds")),
        )
    return cur.rowcount > 0


def milestones() -> list[dict]:
    return [dict(r) for r in connect().execute(
        "SELECT kind, threshold, achieved_at FROM milestones ORDER BY achieved_at DESC"
    )]


def purge_all() -> None:
    conn = connect()
    with conn:
        for table in ("hourly", "key_counts", "shortcut_counts", "app_usage", "milestones"):
            conn.execute("DELETE FROM " + table)
    conn.execute("VACUUM")
