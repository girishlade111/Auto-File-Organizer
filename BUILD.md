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

## Signing a release (Certum SimplySign cloud certificate)

This project uses Certum's **Open Source Code Signing in the Cloud**
certificate. There is deliberately **no local `.pfx` file**: the private key
lives in Certum's cloud HSM and reaches `signtool` through the SimplySign
Desktop virtual token (CSP), which exposes the certificate in the Windows
certificate store. `signtool` therefore selects the cert with `/n` (subject
name) — never `/f <path>`. This matches Certum's own documented syntax
(`signtool sign /n "<owner>" ...`, see Certum's "Code Signing – signing the
code using tools like Signtool" instruction) and real-world SimplySign OSS
usage (`/n "Open Source Developer"`).

Sign **both** the app exe and the installer — SmartScreen evaluates each
independently.

### One-time setup (manual)

1. Buy/activate "Open Source Code Signing in the Cloud" and complete Certum's
   identity verification. The issued subject contains "Open Source Developer"
   plus your name.
2. Install **SimplySign Mobile** (Android/iOS) and activate it with the QR
   flow from Certum's email. Note: it activates on ONE device only.
3. Install **SimplySign Desktop** on the build machine (during setup, unselect
   "proCertum SmartSign"). Log in with your SimplySign email + the mobile-app
   OTP. This registers the virtual token that `signtool` uses.
4. Verify the certificate is visible to Windows with a private key:
   ```powershell
   Get-ChildItem Cert:\CurrentUser\My |
     Where-Object { $_.Subject -like '*Open Source Developer*' } |
     Select-Object Subject, Thumbprint, HasPrivateKey
   ```
   `HasPrivateKey` must be True.

### Signing

```powershell
.\build.ps1   # signs automatically when the certificate above is present
```

Equivalent manual commands (subject name from the store, not a file):

```powershell
signtool sign /n "Open Source Developer" /fd sha256 /tr http://timestamp.digicert.com /td sha256 dist\FileOrganizer\FileOrganizer.exe
signtool sign /n "Open Source Developer" /fd sha256 /tr http://timestamp.digicert.com /td sha256 installer\Output\Setup-FileOrganizer.exe
```

If several matching certificates exist (e.g. old + renewed side by side), pin
the exact one by thumbprint instead of `/n`:
`signtool sign /sha1 <THUMBPRINT> /fd sha256 /tr ... <file>`.

### Interactive confirmation (important)

Each `signtool` invocation triggers a SimplySign approval on your phone
(PIN/mobile confirmation) — `build.ps1` prints a "check your phone" warning
before calling signtool so it never looks hung. Tip: SimplySign Desktop's
Options menu has "Enable PIN cache for CSP/KSP-based applications" (~3-hour
cache), so signing both files normally needs just one phone approval.
Fully unattended CI signing exists (TOTP-based tooling that drives Certum's
cloud API without the Desktop client), but that is overkill for a solo dev's
local release builds — revisit only if releases move to CI.

Verify afterwards:

```powershell
Get-AuthenticodeSignature dist\FileOrganizer\FileOrganizer.exe, installer\Output\Setup-FileOrganizer.exe | Select-Object Path, Status
```

Rules:

- SimplySign account credentials, OTP/TOTP secrets, and your PIN must **never**
  be committed or hardcoded anywhere — they live on your phone and in your
  head, not in the repo. (There is no password to configure: with the store
  based `/n` flow, approval happens on the phone, not via a `/p` flag.)
- Never commit certificate files: `.gitignore` blocks `*.pfx` / `*.p12`
  (retained in case some other signing method is ever used).
- Timestamping (`/tr ... /td sha256`) keeps existing installs trusted after the
  certificate itself expires.
- With no certificate configured the script prints a skip message and exits 0 —
  the unsigned output is byte-for-byte the normal dev build.
