"""User settings persistence (watched folders, ignore list, live-mode flag).

Kept separate from config.json: config.json is the backend category map,
settings.json is user state written by the GUI.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = APP_DIR / "settings.json"


def _log_settings_problem(message: str) -> None:
    """Best-effort logging to activity.log; never raises."""
    try:
        from organizer import log_activity
        log_activity(message)
    except Exception:
        pass


def _atomic_write_json(path: Path, data) -> None:
    """Write JSON crash-safely: temp file + fsync + os.replace.

    Raises OSError on failure so callers can report it (never silent).
    """
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def default_downloads_folder() -> str:
    return str(Path.home() / "Downloads")


def load_settings() -> dict:
    defaults = {
        "watched_folders": [default_downloads_folder()],
        "ignore_list": [],
        "live_mode": True,
        "onboarding_done": False,
    }
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            defaults.update(data)
    except json.JSONDecodeError:
        _log_settings_problem(
            "SETTINGS FILE WAS CORRUPT; reset to defaults to protect your files.")
    except OSError:
        pass
    # Normalize types (guard against hand-edited / corrupt files).
    if not isinstance(defaults.get("watched_folders"), list):
        defaults["watched_folders"] = [default_downloads_folder()]
    if not isinstance(defaults.get("ignore_list"), list):
        defaults["ignore_list"] = []
    defaults["live_mode"] = bool(defaults.get("live_mode", True))
    defaults["onboarding_done"] = bool(defaults.get("onboarding_done", False))
    return defaults


def save_settings(settings: dict) -> None:
    try:
        _atomic_write_json(SETTINGS_PATH, settings)
    except OSError as exc:
        _log_settings_problem(f"ERROR: could not save settings: {exc}")
