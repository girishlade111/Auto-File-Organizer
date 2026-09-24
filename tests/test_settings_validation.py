"""Entry-level validation for settings.json (settings._clean_str_list).

Junk entries (non-strings, blanks) must be dropped with a log line; surviving
entries must be stored trimmed. Uses tmp paths only — the real repo tree
(settings.json, logs/) is never touched.
"""
from __future__ import annotations

import json

import pytest

import organizer
import settings as app_settings


@pytest.fixture()
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(organizer, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(organizer, "ACTIVITY_LOG", tmp_path / "logs" / "activity.log")
    yield tmp_path


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_drops_junk_and_logs(isolated_settings):
    _write(app_settings.SETTINGS_PATH, {
        "watched_folders": ["C:\\valid", 123, None, "", "   "],
        "ignore_list": ["ok", 42, ""],
        "live_mode": True, "onboarding_done": True})
    s = app_settings.load_settings()
    assert s["watched_folders"] == ["C:\\valid"]
    assert s["ignore_list"] == ["ok"]
    log = organizer.ACTIVITY_LOG.read_text(encoding="utf-8")
    assert "dropped 4 invalid entries from 'watched_folders'" in log
    assert "dropped 2 invalid entries from 'ignore_list'" in log


def test_strips_surviving_entries(isolated_settings):
    _write(app_settings.SETTINGS_PATH, {
        "watched_folders": ["  C:\\Data  "],
        "ignore_list": ["\tmy-folder\n"],
        "live_mode": True, "onboarding_done": True})
    s = app_settings.load_settings()
    assert s["watched_folders"] == ["C:\\Data"]
    assert s["ignore_list"] == ["my-folder"]


def test_valid_config_round_trips_untouched(isolated_settings):
    payload = {"watched_folders": ["C:\\a", "D:\\b"], "ignore_list": ["x"],
               "live_mode": False, "onboarding_done": True}
    _write(app_settings.SETTINGS_PATH, payload)
    s = app_settings.load_settings()
    assert s["watched_folders"] == ["C:\\a", "D:\\b"]
    assert s["ignore_list"] == ["x"]
    assert s["live_mode"] is False
