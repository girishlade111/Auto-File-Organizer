#Requires -Version 5.1
<#
.SYNOPSIS
  Full build pipeline: PyInstaller -> Inno Setup -> (optional) Authenticode sign.
.DESCRIPTION
  Unsigned by default so the local dev workflow keeps working with zero setup.
  To sign a release build, complete the one-time SimplySign setup in BUILD.md
  (mobile app + Desktop login). No files or passwords to configure: the script
  finds the certificate in the Windows certificate store automatically.
  Optional override: $env:FILEORGANIZER_CERT_SUBJECT (default
  'Open Source Developer') if your certificate subject differs.
  See BUILD.md for the full pipeline documentation.
#>
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $MyInvocation.MyCommand.Path)

# Runs a native exe step. Temporarily relaxes $ErrorActionPreference because
# PowerShell 5.1 turns a native tool's stderr lines into terminating errors
# under 'Stop' (pyinstaller/iscc log to stderr) — which would abort the build
# whenever output is captured or redirected. Failure is still detected via
# $LASTEXITCODE immediately after the call.
function Invoke-Native($label, [scriptblock]$body) {
    Write-Host "`n=== $label ===" -ForegroundColor Cyan
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $body } finally { $ErrorActionPreference = $prevEap }
    if ($LASTEXITCODE -ne 0) { throw "$label failed (exit $LASTEXITCODE)" }
}

# -- 1. PyInstaller -----------------------------------------------------------
try { Get-Command pyinstaller -ErrorAction Stop | Out-Null }
catch { throw "pyinstaller not found. Run: pip install -r requirements.txt; pip install pyinstaller" }
Invoke-Native 'PyInstaller (onedir, windowed, bundles config.json)' {
    pyinstaller -y --onedir --windowed --name FileOrganizer --add-data 'config.json;.' main.py
}
if (-not (Test-Path -LiteralPath 'dist\FileOrganizer\_internal\config.json')) {
    throw 'config.json was not bundled (expected at dist\FileOrganizer\_internal\config.json)'
}

# -- 2. Inno Setup ------------------------------------------------------------
$iscc = $null
foreach ($candidate in @(
    (Get-Command iscc -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
    'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
    'C:\Program Files\Inno Setup 6\ISCC.exe',
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'))) {
    if ($candidate -and (Test-Path -LiteralPath $candidate)) { $iscc = $candidate; break }
}
if (-not $iscc) { throw 'ISCC.exe not found. Install Inno Setup 6: https://jrsoftware.org/isdl.php' }
Invoke-Native "Inno Setup ($iscc)" { & $iscc 'installer\FileOrganizer.iss' }

$installer = 'installer\Output\Setup-FileOrganizer.exe'
if (-not (Test-Path -LiteralPath $installer)) { throw "expected installer missing: $installer" }

# -- 3. Optional Authenticode signing (Certum SimplySign cloud cert) -----------
# No local .pfx with SimplySign: the cert lives in the Windows certificate
# store via the SimplySign Desktop virtual token, and signtool selects it by
# subject name (/n). Override the expected subject if yours differs:
#   $env:FILEORGANIZER_CERT_SUBJECT = '...'
$certSubject = $env:FILEORGANIZER_CERT_SUBJECT
if ([string]::IsNullOrWhiteSpace($certSubject)) { $certSubject = 'Open Source Developer' }
$storeCerts = @(Get-ChildItem -Path 'Cert:\CurrentUser\My' -ErrorAction SilentlyContinue |
    Where-Object { $_.Subject -like "*$certSubject*" -and $_.HasPrivateKey })
if ($storeCerts.Count -eq 0) {
    Write-Host "`nSkipping code signing: no '$certSubject' certificate with a private key in Cert:\CurrentUser\My (unsigned dev build)." -ForegroundColor Yellow
    Write-Host 'To sign: install SimplySign Desktop, log in (email + mobile OTP), then re-run. See BUILD.md.' -ForegroundColor Yellow
}
elseif ($storeCerts.Count -gt 1) {
    Write-Host "`nSkipping code signing: $($storeCerts.Count) certificates match '$certSubject'." -ForegroundColor Yellow
    $storeCerts | Select-Object Subject, Thumbprint | Format-Table -AutoSize | Out-String | Write-Host
    Write-Host 'Set FILEORGANIZER_CERT_SUBJECT to match exactly one, or sign manually with /sha1 <thumbprint>. Unsigned dev build continues below.' -ForegroundColor Yellow
}
else {
    $signtool = $null
    $sdkTools = @()
    if (Test-Path -LiteralPath "${env:ProgramFiles(x86)}\Windows Kits\10\bin") {
        $sdkTools = Get-ChildItem -LiteralPath "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Directory |
            Sort-Object Name -Descending |
            ForEach-Object { Join-Path $_.FullName 'x64\signtool.exe' }
    }
    foreach ($candidate in @((Get-Command signtool -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)) + $sdkTools) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) { $signtool = $candidate; break }
    }
    if (-not $signtool) { throw 'signtool.exe not found. Install the Windows SDK: https://developer.microsoft.com/windows/downloads/windows-sdk/' }
    Write-Host "`nSigning requires SimplySign mobile app confirmation - check your phone when prompted. (Tip: enable PIN cache in SimplySign Desktop Options to approve once.)" -ForegroundColor Yellow
    foreach ($target in @('dist\FileOrganizer\FileOrganizer.exe', $installer)) {
        Invoke-Native "Signing $target" {
            & $signtool sign /n $certSubject /fd sha256 /tr http://timestamp.digicert.com /td sha256 $target
        }
    }
    Write-Host "`nBoth the app exe and the installer are signed." -ForegroundColor Green
}

Write-Host "`nBuild complete (unsigned unless a certificate was configured):" -ForegroundColor Green
Get-Item -LiteralPath 'dist\FileOrganizer\FileOrganizer.exe', $installer |
    Select-Object FullName, @{n = 'MB'; e = { [math]::Round($_.Length / 1MB, 1) } } |
    Format-Table -AutoSize | Out-String | Write-Host
