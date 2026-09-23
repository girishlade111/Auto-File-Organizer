"""Real-time folder monitoring (watchdog, live mode — no polling).

One Observer per watched folder. New top-level files are organized after a
short settle delay so in-progress downloads/copies are not grabbed mid-write.
Each callback runs in its own daemon thread so a slow file never blocks others.

The handler deliberately ignores:
  * directory events (subfolders are never organized — SafeZone rule),
  * files inside category output folders or protected project folders,
  * incomplete downloads / OS bookkeeping files (organizer double-checks).
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
    _WATCHDOG_AVAILABLE = True
except ImportError:  # GUI still loads; status bar shows Error with guidance.
    FileSystemEventHandler = object  # type: ignore
    Observer = None  # type: ignore
    _WATCHDOG_AVAILABLE = False

SETTLE_DELAY = 1.5  # seconds to wait before touching a brand-new file


def watchdog_available() -> bool:
    return _WATCHDOG_AVAILABLE


class OrganizerEventHandler(FileSystemEventHandler):
    def __init__(self, watched_root: str | Path,
                 on_result: Callable[[dict], None] | None = None,
                 get_ignore_list: Callable[[], list] | None = None):
        super().__init__()
        self.root = Path(watched_root)
        self.on_result = on_result
        self.get_ignore_list = get_ignore_list
        self._timers: dict[str, threading.Timer] = {}
        self._timers_lock = threading.Lock()

    # -- watchdog callbacks -------------------------------------------------
    def on_created(self, event):  # noqa: N802 (watchdog naming)
        if event.is_directory:
            self._emit({"status": "protected-check", "src": event.src_path,
                        "reason": "new folder — checking SafeZone"})
            return
        self._schedule(event.src_path)

    def on_moved(self, event):  # noqa: N802 — e.g. browser download finalize
        if event.is_directory:
            return
        dest = getattr(event, "dest_path", None) or event.src_path
        self._schedule(dest)

    # -- internals ----------------------------------------------------------
    def _schedule(self, src_path: str) -> None:
        with self._timers_lock:
            old = self._timers.pop(src_path, None)
            if old is not None:
                old.cancel()
            timer = threading.Timer(SETTLE_DELAY, self._handle, args=(src_path,))
            timer.daemon = True
            self._timers[src_path] = timer
            timer.start()

    def _handle(self, src_path: str) -> None:
        from project_detector import is_protected_folder
        import organizer as org

        with self._timers_lock:
            self._timers.pop(src_path, None)
        src = Path(src_path)
        try:
            # Ignore anything not directly inside the watched root (this also
            # covers files created inside category folders / project folders).
            if not src.parent.resolve() == self.root.resolve():
                # A new subfolder itself: report its SafeZone status for the feed.
                if src.is_dir() or (not src.exists() and src.suffix == ""):
                    try:
                        protected, reason = is_protected_folder(
                            src, self.get_ignore_list() if self.get_ignore_list else None)
                        if protected:
                            self._emit({"status": "protected", "src": str(src),
                                        "dst": None, "reason": reason,
                                        "name": src.name})
                    except OSError:
                        pass
                return
            if not src.is_file():
                return
            result = org.organize_file(src, self.root, wait_for_stable=True)
            self._emit(result)
        except OSError as exc:
            self._emit({"status": "error", "src": src_path,
                        "dst": None, "reason": str(exc)})

    def _emit(self, result: dict) -> None:
        if self.on_result is not None:
            try:
                self.on_result(result)
            except Exception:
                pass


class FolderWatcherManager:
    """Owns one Observer per watched folder; safe to use from the GUI thread."""

    def __init__(self, on_result: Callable[[dict], None] | None = None,
                 get_ignore_list: Callable[[], list] | None = None):
        self.on_result = on_result
        self.get_ignore_list = get_ignore_list
        self._observers: dict[str, Observer] = {}
        self._lock = threading.Lock()
        self._paused = False

    # -- lifecycle ----------------------------------------------------------
    def add_folder(self, folder: str | Path) -> bool:
        """Register one folder for live watching.

        Never starts an Observer while paused: when paused, returns False
        without creating anything — resume_all() will add the folder later.
        (Previously this created, started, then immediately stopped the
        Observer, so live mode silently watched nothing.)
        """
        if not watchdog_available():
            return False
        key = str(Path(folder).resolve())
        with self._lock:
            if key in self._observers:
                return True  # already watching this folder
            if self._paused:
                return False  # paused — resume_all() picks this up later
        handler = OrganizerEventHandler(
            folder, on_result=self.on_result,
            get_ignore_list=self.get_ignore_list)
        observer = Observer()
        observer.schedule(handler, str(folder), recursive=False)
        try:
            observer.start()
        except OSError:
            return False
        with self._lock:
            if self._paused:
                # Lost a race with pause_all(): don't leak a live observer.
                raced = True
            else:
                self._observers[key] = observer
                raced = False
        if raced:
            observer.stop()
            observer.join(timeout=5)
            return False
        return True

    def remove_folder(self, folder: str | Path) -> None:
        key = str(Path(folder).resolve())
        with self._lock:
            observer = self._observers.pop(key, None)
        if observer is not None:
            observer.stop()
            observer.join(timeout=5)

    def pause_all(self) -> None:
        with self._lock:
            observers, self._observers = self._observers, {}
            self._paused = True
        for obs in observers.values():
            obs.stop()
            obs.join(timeout=5)

    def resume_all(self, folders: list[str | Path]) -> None:
        with self._lock:
            self._paused = False
        for folder in folders:
            self.add_folder(folder)

    def stop_all(self) -> None:
        self.pause_all()
        with self._lock:
            self._paused = False

    # -- state --------------------------------------------------------------
    @property
    def paused(self) -> bool:
        with self._lock:
            return self._paused

    def watched_count(self) -> int:
        with self._lock:
            return len(self._observers)

    def is_watching(self, folder: str | Path) -> bool:
        key = str(Path(folder).resolve())
        with self._lock:
            return key in self._observers
