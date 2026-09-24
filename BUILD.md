# Build, packaging & code signing — Auto File Organizer

The one-command pipeline is `build.ps1` (Windows PowerShell 5.1+). It runs
PyInstaller → Inno Setup → optional Authenticode signing, and works fully
**unsigned** for day-to-day dev. This file documents each stage.

## Prerequisites

- Python 3.14+ with `pip install -r requirements.txt` plus `pip install pyinstaller`
- [Inno Setup 6](https://jrsoftware.org/isdl.php) (`ISCC.exe`; per-user install is fine —
  the script checks `PATH`, both Program Files locations, and `%LOCALAPPDATA%`)
- For signing only: [Windows SDK](https://developer.microsoft.com/windows/downloads/windows-sdk/)
  (provides `signtool.exe`) plus a code-signing certificate (see below)

## Unsigned build (default)

```powershell
.\build.ps1
```

Equivalent manual steps (exactly what the script runs):

```powershell
pyinstaller -y --onedir --windowed --name FileOrganizer --add-data "config.json;." main.py
iscc installer\FileOrganizer.iss
```

Notes:

- `--add-data "config.json;."` is required, not optional: without it the frozen
  app finds no category map and files everything under "Others". The bundle is
  verified to contain `dist\FileOrganizer\_internal\config.json` before compiling.
- `installer\FileOrganizer.iss` uses `Source: "..\dist\FileOrganizer\*"` because
  Inno resolves relative `Source` paths against the **script's directory**
  (`installer\`), not the repo root — `dist\...` without the `..\` fails with
  "No files found matching ...\installer\dist\FileOrganizer\*".
- The installer lands at `installer\Output\Setup-FileOrganizer.exe`
  (~24 MB for ~74 MB of onedir output). `Output/` is gitignored.
- Install behavior (per `installer\FileOrganizer.iss`): per-user install to
  `%LOCALAPPDATA%\Programs\Auto File Organizer` (`PrivilegesRequired=lowest`),
  Start Menu entry, optional Desktop icon (unchecked by default), Startup-folder
  shortcut with `--tray` created when "Start automatically when Windows starts"
  stays checked (default), post-install auto-launch. **No registry Run key** —
  autostart is a `shell:startup` shortcut by design (see the header comment in
  the `.iss`). Silent install for testing:
  `Setup-FileOrganizer.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART`.

## Signing a release (activate once a certificate exists)

Sign **both** the app exe and the installer — SmartScreen evaluates each
independently:

```powershell
$env:FILEORGANIZER_CERT_PFX = 'C:\path\to\cert.pfx'
$env:FILEORGANIZER_CERT_PASSWORD = '...'   # or leave unset to be prompted
.\build.ps1
```

Equivalent manual commands:

```powershell
signtool sign /f $env:FILEORGANIZER_CERT_PFX /p $env:FILEORGANIZER_CERT_PASSWORD /fd sha256 /tr http://timestamp.digicert.com /td sha256 dist\FileOrganizer\FileOrganizer.exe
signtool sign /f $env:FILEORGANIZER_CERT_PFX /p $env:FILEORGANIZER_CERT_PASSWORD /fd sha256 /tr http://timestamp.digicert.com /td sha256 installer\Output\Setup-FileOrganizer.exe
```

Verify afterwards:

```powershell
Get-AuthenticodeSignature dist\FileOrganizer\FileOrganizer.exe, installer\Output\Setup-FileOrganizer.exe | Select-Object Path, Status
```

Rules:

- The certificate password must **never** be committed or hardcoded — env var
  or interactive prompt only.
- Never commit certificate files: `.gitignore` blocks `*.pfx` / `*.p12`.
- Timestamping (`/tr ... /td sha256`) keeps existing installs trusted after the
  certificate itself expires.
- With no certificate configured the script prints a skip message and exits 0 —
  the unsigned output is byte-for-byte the normal dev build.
