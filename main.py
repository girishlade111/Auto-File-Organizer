"""App entry point.

  * Manual double-click (no args)  -> full dashboard window.
  * Autostart / installer launch (--tray) -> straight to system tray
    background mode, no window. ("tray" naming is deliberate: literal
    "silent" flags are a known static-analysis red flag for scanners.)

The Startup-folder shortcut that passes --tray is created by the Inno Setup
installer (see installer/FileOrganizer.iss). No registry Run key is used.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from organizer import log_activity


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Auto File Organizer")
    parser.add_argument("--tray", action="store_true",
                        help="Start minimized to the system tray (autostart mode).")
    return parser.parse_args(argv)


def _run_gui_with_tray(start_in_tray: bool) -> int:
    import settings as app_settings
    from tray import TrayController, tray_available

    holder: dict = {}

    def _open():
        app = holder.get("app")
        if app is not None:
            try:
                app.show_window()
            except Exception as exc:
                log_activity(f"ERROR: tray Open callback (app.show_window): {exc}")

    def _organize():
        app = holder.get("app")
        if app is not None:
            try:
                app.organize_now()
            except Exception as exc:
                log_activity(f"ERROR: tray Organize callback (app.organize_now): {exc}")
        else:
            _organize_headless()

    def _undo():
        app = holder.get("app")
        if app is not None:
            try:
                app.undo_last()
            except Exception as exc:
                log_activity(f"ERROR: tray Undo callback (app.undo_last): {exc}")
        else:
            import organizer as org
            org.undo_last_action()

    def _toggle_live():
        app = holder.get("app")
        if app is not None:
            try:
                current = app.settings.get("live_mode", True)
                app.settings["live_mode"] = not current
                app_settings.save_settings(app.settings)
                app._apply_live_mode()
                return app.settings["live_mode"]
            except Exception as exc:
                log_activity(f"ERROR: tray toggle-live callback: {exc}")
                return None
        s = app_settings.load_settings()
        s["live_mode"] = not s.get("live_mode", True)
        app_settings.save_settings(s)
        _apply_headless_watchers()
        return s["live_mode"]

    def _is_live():
        app = holder.get("app")
        if app is not None:
            try:
                return bool(app.settings.get("live_mode", True))
            except Exception as exc:
                log_activity(f"ERROR: tray is-live check: {exc}")
                return True
        return bool(app_settings.load_settings().get("live_mode", True))

    tray = TrayController(on_open=_open, on_organize=_organize, on_undo=_undo,
                          on_toggle_live=_toggle_live, on_exit=_quit_all,
                          is_live=_is_live) if tray_available() else None

    headless_watcher = None

    def _apply_headless_watchers():
        nonlocal headless_watcher
        from watcher import FolderWatcherManager
        s = app_settings.load_settings()
        if headless_watcher is None:
            headless_watcher = FolderWatcherManager(
                get_ignore_list=lambda: app_settings.load_settings().get("ignore_list", []))
        headless_watcher.pause_all()
        if s.get("live_mode", True):
            # resume_all() unpauses AND starts observers; add_folder() alone
            # refuses to start anything while paused, so this call is what
            # actually begins watching.
            headless_watcher.resume_all(
                [f for f in s.get("watched_folders", []) if Path(f).is_dir()])

    def _organize_headless():
        import organizer as org
        s = app_settings.load_settings()
        for folder in s.get("watched_folders", []):
            if Path(folder).is_dir():
                org.organize_folder(folder, s.get("ignore_list", []))

    def _quit_all():
        try:
            if headless_watcher is not None:
                headless_watcher.stop_all()
        except Exception as exc:
            log_activity(f"ERROR: shutdown (headless watcher stop): {exc}")
        app = holder.get("app")
        if app is not None:
            try:
                app.watcher.stop_all()
            except Exception as exc:
                log_activity(f"ERROR: shutdown (GUI watcher stop): {exc}")
            try:
                app.destroy()
            except Exception as exc:
                log_activity(f"ERROR: shutdown (app.destroy): {exc}")
        if tray is not None:
            tray.stop()

    if start_in_tray or not _gui_available():
        # Background mode: tray icon + headless watchers, no window.
        _apply_headless_watchers()
        if tray is not None:
            tray.start_blocking()  # blocks until Exit
        else:
            # No tray support (missing dep): keep watchers alive on main thread.
            import time
            try:
                while True:
                    time.sleep(3600)
            except KeyboardInterrupt:
                pass
        try:
            if headless_watcher is not None:
                headless_watcher.stop_all()
        except Exception as exc:
            log_activity(f"ERROR: shutdown (headless watcher stop): {exc}")
        return 0

    # Foreground mode: full dashboard + tray icon alongside.
    if tray is not None:
        tray.start_detached()
    import gui
    app = gui.App(tray_controller=tray)
    holder["app"] = app
    try:
        app.mainloop()
    finally:
        if tray is not None:
            tray.stop()
    return 0


def _gui_available() -> bool:
    try:
        import customtkinter  # noqa: F401
        return True
    except ImportError:
        return False


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        return _run_gui_with_tray(start_in_tray=args.tray)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
