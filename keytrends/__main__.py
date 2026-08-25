"""Entry point: start the tracker, the local dashboard, and the tray icon."""
from __future__ import annotations

import argparse
import socket
import sys
import time
import webbrowser

from . import config, db, server
from .tracker import get_tracker


def _port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex((host, port)) != 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="keytrends",
        description="Local keyboard and mouse analytics. Counts only -- never the text you type.",
    )
    parser.add_argument("--port", type=int, help="port for the dashboard")
    parser.add_argument("--background", action="store_true",
                        help="start silently, without opening the dashboard")
    parser.add_argument("--no-tray", action="store_true",
                        help="run in the console instead of the system tray")
    parser.add_argument("--paused", action="store_true",
                        help="start with tracking paused")
    args = parser.parse_args(argv)

    settings = config.load()
    host = settings.get("host", "127.0.0.1")
    port = args.port or int(settings.get("port", 8731))
    if args.port:
        config.save({"port": args.port})

    if not _port_available(host, port):
        url = f"http://{host}:{port}/"
        print(f"KeyTrends is already running at {url}", file=sys.stderr)
        if not args.background:
            webbrowser.open(url)
        return 1

    db.init()
    tracker = get_tracker()
    if args.paused:
        tracker.set_paused(True)
    tracker.start()
    server.run_in_thread()

    url = f"http://{host}:{port}/"
    time.sleep(0.6)  # let Flask bind before anything tries to open the page
    print(f"KeyTrends is tracking. Dashboard: {url}")

    should_open = not args.background and settings.get("open_dashboard_on_start", True)

    if args.no_tray:
        if should_open:
            webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping...")
            tracker.stop()
        return 0

    from .tray import TrayApp

    tray = TrayApp(url)
    if should_open:
        webbrowser.open(url)
    try:
        tray.run()
    except KeyboardInterrupt:
        tracker.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
