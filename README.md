# Auto File Organizer

**The only auto-organizer that knows what NOT to touch.**

Auto File Organizer watches your Downloads (or any folder you pick) and tidies new files into category subfolders — Images, Documents, Presentations, Archives, Programs — automatically, in the background. Coding projects are never touched thanks to **SafeZone Detection**.

- No technical knowledge needed: no terminal, no config editing, no jargon.
- Runs in the system tray, starts with Windows, zero maintenance after install.
- One-click **Undo** + a plain-language **Activity Feed** so you always know what happened.

## SafeZone Detection (the moat)

A folder is auto-protected — skipped entirely, including everything inside it — when it contains:

- a `.git` folder, `package.json`, `requirements.txt`, `venv/`, `.env`, `node_modules/`, `.vscode/`, or
- a mix of code files (`.py`, `.js`, `.java`, …)

Plus a manual **Ignore List** for anything you want skipped on top of auto-detection. Protected items show as `🛡️ name skipped (protected)` in the Activity Feed with a plain-language reason.

Only loose, top-level files are ever moved. Subfolder contents are never reorganized.

## Install (end users)

1. Download `Setup-FileOrganizer.exe` from Releases and run it.
2. Keep **"Start automatically when Windows starts"** checked (default).
3. On first launch: Get Started → pick a folder → Start Organizing. Done — you'll never need to open it again.

### Why did Windows show a warning?

Early releases may show a SmartScreen **"Unknown Publisher"** prompt until the app builds download reputation — this is normal for new independent software, not a sign of malware.

1. Click **More info**.
2. Click **Run anyway**.

The app is open-source: every file it moves is listed in the Activity Feed and reversible with **Undo**. Auto-start uses a plain Startup-folder shortcut (no registry tricks), and the app never touches your code folders.

## Run from source (developers)

```powershell
pip install -r requirements.txt
python main.py            # dashboard window
python main.py --tray     # background tray mode (what autostart uses)
```

Build:

```powershell
pyinstaller --onedir --windowed --name FileOrganizer --add-data "config.json;." main.py
iscc installer\FileOrganizer.iss
```

> Note: no `--icon` flag — the tray icon is generated programmatically at runtime via `make_icon_image()`. To use a custom icon, drop an `assets\icon.ico` into the repo and add `--icon assets\icon.ico` to the PyInstaller command.

Full pipeline (one command, optional code signing): `.\build.ps1` — see `BUILD.md`.

Run tests (SafeZone Detection suite):

```powershell
pip install -r requirements-dev.txt
pytest
```

## Project layout

```
organizer.py         - core file-moving logic (safety rules live here)
project_detector.py  - SafeZone Detection (get this right before anything else)
watcher.py           - watchdog real-time monitoring
gui.py               - CustomTkinter onboarding + dashboard
tray.py              - pystray system tray integration
main.py              - entry point (--tray = background mode)
config.json          - extension → category map (backend only)
settings.json        - user state (created on first run)
logs/activity.log   - what was moved / skipped
installer/           - Inno Setup script (Startup-folder autostart)
```

## Tech

Python · watchdog · CustomTkinter · pystray · PyInstaller (`--onedir`) · Inno Setup.
Free tier v1 (matches the LadeStack free+donation pattern). Multi-PC sync of the Ignore List and Pro category presets are reserved for v1.1 — the architecture doesn't block them.
