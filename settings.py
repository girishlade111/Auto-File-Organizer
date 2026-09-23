"""User settings persistence (watched folders, ignore list, live-mode flag).

Kept separate from config.json: config.json is the backend category map,
settings.json is user state written by the GUI.
"""

from __future__ import annotations

import json
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = APP_DIR / "settings.json"


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
    except (OSError, json.JSONDecodeError):
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
        with open(SETTINGS_PATH, "w", encoding="utf-8") as fh:
            json.dump(settings, fh, indent=2)
    except OSError:
        pass
