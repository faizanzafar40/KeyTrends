"""Local Flask dashboard for KeyTrends.

Binds to 127.0.0.1 only -- the dashboard is never exposed to the network.
"""
from __future__ import annotations

import csv
import io
import json
import threading
from datetime import datetime

from flask import Flask, Response, jsonify, render_template, request

from . import autostart, config, db, insights
from .tracker import get_tracker

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

VALID_RANGES = tuple(db.RANGES.keys())
RANGE_LABELS = {
    "today": "day", "7d": "week", "30d": "month",
    "90d": "quarter", "365d": "year", "all": "period",
}


def _requested_range() -> str:
    rng = request.args.get("range", "30d")
    return rng if rng in VALID_RANGES else "30d"


@app.after_request
def _no_store(resp: Response) -> Response:
    # Stats change constantly; never let the browser serve a stale API response.
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/")
def dashboard():
    return render_template("dashboard.html", version=_version())


def _version() -> str:
    from . import __version__
    return __version__


@app.route("/api/data")
def api_data():
    rng = _requested_range()
    start, end = db.range_bounds(rng)
    keys = db.key_counts(start, end)
    return jsonify({
        "range": rng,
        "start": start,
        "end": end,
        "summary": insights.summary(start, end),
        "insights": insights.build(start, end, RANGE_LABELS.get(rng, "period")),
        "daily": db.daily_series(start, end),
        "hourly": db.hourly_profile(start, end),
        "matrix": db.dow_hour_matrix(start, end),
        "dow": db.dow_totals(start, end),
        "keys": [{"key": k["key"], "label": insights.key_label(k["key"]), "count": k["count"]}
                 for k in keys],
        "apps": db.app_usage(start, end, limit=8),
        "shortcuts": db.shortcut_counts(start, end, limit=10),
        "records": db.records(),
        "streaks": db.streaks(),
        "milestones": db.milestones(),
        "first_run": db.first_run(),
        "settings": _public_settings(),
    })


@app.route("/api/live")
def api_live():
    tracker = get_tracker()
    data = tracker.live()
    data["new_milestones"] = tracker.new_milestones[:]
    tracker.new_milestones.clear()
    return jsonify(data)


def _public_settings() -> dict:
    settings = config.load()
    settings["autostart"] = autostart.is_enabled()
    settings.pop("host", None)
    return settings


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    if request.method == "GET":
        return jsonify(_public_settings())

    payload = request.get_json(silent=True) or {}
    updates = {}
    for key in ("track_key_detail", "track_apps", "track_shortcuts",
                "open_dashboard_on_start", "milestone_notifications"):
        if key in payload:
            updates[key] = bool(payload[key])
    if "excluded_apps" in payload and isinstance(payload["excluded_apps"], list):
        updates["excluded_apps"] = [str(a).strip() for a in payload["excluded_apps"]
                                    if str(a).strip()]
    if updates:
        config.save(updates)

    if "paused" in payload:
        get_tracker().set_paused(bool(payload["paused"]))
    if "autostart" in payload:
        autostart.set_enabled(bool(payload["autostart"]))

    return jsonify(_public_settings())


@app.route("/api/export")
def api_export():
    rng = _requested_range()
    start, end = db.range_bounds(rng)
    fmt = request.args.get("format", "csv").lower()
    stamp = datetime.now().strftime("%Y%m%d")

    if fmt == "json":
        payload = {
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "range": {"name": rng, "start": start, "end": end},
            "summary": insights.summary(start, end),
            "daily": db.daily_series(start, end),
            "hourly_profile": db.hourly_profile(start, end),
            "keys": db.key_counts(start, end),
            "shortcuts": db.shortcut_counts(start, end, limit=1000),
            "apps": db.app_usage(start, end, limit=1000),
            "records": db.records(),
            "streaks": db.streaks(),
        }
        return Response(
            json.dumps(payload, indent=2),
            mimetype="application/json",
            headers={"Content-Disposition":
                     f'attachment; filename="keytrends-{rng}-{stamp}.json"'},
        )

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["date", "keystrokes", "clicks", "scrolls",
                     "mouse_pixels", "active_seconds", "peak_wpm"])
    for row in db.daily_series(start, end):
        writer.writerow([row["day"], row["keystrokes"], row["clicks"], row["scrolls"],
                         round(row["mouse_px"] or 0), row["active_seconds"],
                         round(row["peak_wpm"] or 0, 1)])
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition":
                 f'attachment; filename="keytrends-{rng}-{stamp}.csv"'},
    )


@app.route("/api/reset", methods=["POST"])
def api_reset():
    payload = request.get_json(silent=True) or {}
    if payload.get("confirm") != "DELETE":
        return jsonify({"error": "confirmation required"}), 400
    get_tracker().flush()
    db.purge_all()
    return jsonify({"ok": True})


def run(host: str | None = None, port: int | None = None) -> None:
    settings = config.load()
    app.run(
        host=host or settings.get("host", "127.0.0.1"),
        port=port or int(settings.get("port", 8731)),
        debug=False,
        use_reloader=False,
        threaded=True,
    )


def run_in_thread() -> threading.Thread:
    thread = threading.Thread(target=run, daemon=True, name="keytrends-server")
    thread.start()
    return thread
