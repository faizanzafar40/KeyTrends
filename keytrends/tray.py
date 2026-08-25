"""System tray icon: the app's only visible surface while it runs."""
from __future__ import annotations

import threading
import webbrowser

import pystray
from PIL import Image, ImageDraw

from . import autostart, config
from .tracker import get_tracker

BLUE = (42, 120, 214)
LIGHT = (252, 252, 251)
DIM = (137, 135, 129)


def _icon_image(paused: bool = False) -> Image.Image:
    """A small keyboard glyph, greyed out while tracking is paused."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    body = DIM if paused else BLUE
    draw.rounded_rectangle([4, 14, 60, 50], radius=8, fill=body)
    # Three rows of keys.
    for row, (y0, y1) in enumerate(((21, 27), (30, 36))):
        for col in range(5):
            x0 = 10 + col * 9 + (4 if row else 0)
            if x0 + 6 <= 56:
                draw.rounded_rectangle([x0, y0, x0 + 6, y1], radius=1, fill=LIGHT)
    draw.rounded_rectangle([18, 39, 46, 45], radius=1, fill=LIGHT)  # space bar
    return img


class TrayApp:
    def __init__(self, url: str) -> None:
        self.url = url
        self.tracker = get_tracker()
        self.icon = pystray.Icon(
            "KeyTrends", _icon_image(self.tracker.paused), "KeyTrends", self._menu()
        )
        self._refresh_stop = threading.Event()

    # ------------------------------------------------------------ menu

    def _menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem("Open dashboard", self._open, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(self._today_label, None, enabled=False),
            pystray.MenuItem(self._speed_label, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Pause tracking", self._toggle_pause,
                checked=lambda item: self.tracker.paused,
            ),
            pystray.MenuItem(
                "Start with Windows", self._toggle_autostart,
                checked=lambda item: autostart.is_enabled(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit KeyTrends", self._quit),
        )

    def _today_label(self, _item=None) -> str:
        try:
            live = self.tracker.live()
            return f"Today: {live['keystrokes']:,} keys | {live['clicks']:,} clicks"
        except Exception:
            return "Today: --"

    def _speed_label(self, _item=None) -> str:
        try:
            live = self.tracker.live()
            state = "Paused" if live["paused"] else f"{live['wpm']:.0f} WPM now"
            return f"{state} | active {live['active_seconds'] // 60}m"
        except Exception:
            return ""

    # ------------------------------------------------------------ actions

    def _open(self, *_args) -> None:
        webbrowser.open(self.url)

    def _toggle_pause(self, *_args) -> None:
        self.tracker.set_paused(not self.tracker.paused)
        self.icon.icon = _icon_image(self.tracker.paused)
        self.icon.update_menu()

    def _toggle_autostart(self, *_args) -> None:
        autostart.set_enabled(not autostart.is_enabled())
        self.icon.update_menu()

    def _quit(self, *_args) -> None:
        self._refresh_stop.set()
        try:
            self.tracker.stop()
        finally:
            self.icon.stop()

    def notify(self, title: str, message: str) -> None:
        try:
            self.icon.notify(message, title)
        except Exception:
            pass  # Balloon notifications are best-effort.

    # ------------------------------------------------------------ run

    def _refresh_loop(self) -> None:
        """Keep the live counters in the tray menu and tooltip current."""
        while not self._refresh_stop.wait(5.0):
            try:
                live = self.tracker.live()
                self.icon.title = (
                    f"KeyTrends -- {live['keystrokes']:,} keys, {live['clicks']:,} clicks today"
                )
                self.icon.update_menu()
                if config.get("milestone_notifications"):
                    for milestone in self.tracker.new_milestones[:]:
                        self.notify(
                            "KeyTrends milestone",
                            f"{milestone['threshold']:,} {milestone['kind']} reached!",
                        )
                        self.tracker.new_milestones.remove(milestone)
            except Exception:
                pass

    def run(self) -> None:
        threading.Thread(target=self._refresh_loop, daemon=True).start()
        self.icon.run()
