"""System tray integration (pystray).

Menu: Open dashboard, Organize Now, Undo, Pause/Resume, Exit (with a
confirmation dialog so non-technical users can't kill background mode
by accident, while keeping full user control).

The tray icon is drawn programmatically with Pillow — no external .ico
file required for dev; the installer swaps in the branded icon.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

try:
    import pystray
    from pystray import Menu, MenuItem
    from PIL import Image, ImageDraw
    _TRAY_AVAILABLE = True
except ImportError:
    pystray = None  # type: ignore
    Menu = MenuItem = None  # type: ignore
    Image = ImageDraw = None  # type: ignore
    _TRAY_AVAILABLE = False


def tray_available() -> bool:
    return _TRAY_AVAILABLE


def make_icon_image(size: int = 64):
    """Simple folder glyph: blue rounded square + green check accent."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = size // 8
    draw.rounded_rectangle([pad, pad * 2, size - pad, size - pad],
                           radius=size // 8, fill=(37, 99, 235, 255))
    draw.rounded_rectangle([pad, pad, size // 2, pad * 2 + 4],
                           radius=3, fill=(37, 99, 235, 255))
    # green dot = "live"
    r = size // 6
    draw.ellipse([size - pad - r, size - pad - r, size - pad, size - pad],
                 fill=(46, 158, 91, 255))
    return img


class TrayController:
    def __init__(self,
                 on_open: Callable[[], None] | None = None,
                 on_organize: Callable[[], None] | None = None,
                 on_undo: Callable[[], None] | None = None,
                 on_toggle_live: Callable[[], bool | None] | None = None,
                 on_exit: Callable[[], None] | None = None,
                 is_live: Callable[[], bool] | None = None):
        self.on_open = on_open
        self.on_organize = on_organize
        self.on_undo = on_undo
        self.on_toggle_live = on_toggle_live
        self.on_exit = on_exit
        self.is_live = is_live
        self._icon = None
        self._thread: threading.Thread | None = None

    # -- public -----------------------------------------------------------
    def start_detached(self) -> bool:
        """Run the tray icon loop in a daemon thread. Returns False if unavailable."""
        if not tray_available():
            return False
        if self._thread is not None and self._thread.is_alive():
            return True
        self._thread = threading.Thread(target=self._run_blocking, daemon=True)
        self._thread.start()
        return True

    def start_blocking(self) -> None:
        if tray_available():
            self._run_blocking()

    def stop(self) -> None:
        try:
            if self._icon is not None:
                self._icon.stop()
        except Exception:
            pass

    # -- internals ----------------------------------------------------------
    def _live_label(self) -> str:
        try:
            live = self.is_live() if self.is_live else True
        except Exception:
            live = True
        return "Pause auto-organize" if live else "Resume auto-organize"

    def _menu(self):
        def _wrap(fn):
            def _inner(icon, item):
                try:
                    if fn:
                        fn()
                except Exception:
                    pass
            return _inner

        return Menu(
            MenuItem("Open organizer", _wrap(self.on_open), default=True),
            MenuItem("Organize now", _wrap(self.on_organize)),
            MenuItem("Undo last action", _wrap(self.on_undo)),
            Menu.SEPARATOR,
            MenuItem(lambda item: self._live_label(), _wrap(self.on_toggle_live)),
            Menu.SEPARATOR,
            MenuItem("Exit", self._on_exit_clicked),
        )

    def _on_exit_clicked(self, icon, item):
        # Confirmation lives here (tray side) so background-only (--tray)
        # runs are still protected against accidental shutdown.
        try:
            from tkinter import messagebox
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            still = messagebox.askyesno(
                "Exit File Organizer?",
                "File Organizer won't auto-organize new files if closed.\n\n"
                "Still exit?",
                parent=root)
            root.destroy()
            if not still:
                return
        except Exception:
            pass  # no display — treat click as confirmed exit
        try:
            icon.stop()
        except Exception:
            pass
        try:
            if self.on_exit:
                self.on_exit()
        except Exception:
            pass

    def _run_blocking(self) -> None:
        icon_path = Path(__file__).resolve().parent / "assets" / "icon.ico"
        try:
            if icon_path.is_file():
                image = Image.open(str(icon_path))
            else:
                image = make_icon_image()
        except Exception:
            image = make_icon_image()
        self._icon = pystray.Icon("Auto File Organizer", image,
                                  "Auto File Organizer", menu=self._menu())
        try:
            self._icon.run()
        except Exception:
            pass
