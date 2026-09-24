#Requires -Version 5.1
<#
.SYNOPSIS
  Full build pipeline: PyInstaller -> Inno Setup -> (optional) Authenticode sign.
.DESCRIPTION
  Unsigned by default so the local dev workflow keeps working with zero setup.
  To sign a release build, set these BEFORE running (never commit them):
    $env:FILEORGANIZER_CERT_PFX      = full path to the .pfx / .p12 certificate
    $env:FILEORGANIZER_CERT_PASSWORD = certificate password (or leave unset to
                                       be prompted securely at build time)
  See BUILD.md for the full pipeline documentation.
#>
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $MyInvocation.MyCommand.Path)

function Invoke-Step($label, [scriptblock]$body) {
    Write-Host "`n=== $label ===" -ForegroundColor Cyan
    & $body
    if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) { throw "$label failed (exit $LASTEXITCODE)" }
}

# -- 1. PyInstaller -----------------------------------------------------------
try { Get-Command pyinstaller -ErrorAction Stop | Out-Null }
catch { throw "pyinstaller not found. Run: pip install -r requirements.txt; pip install pyinstaller" }
Invoke-Step 'PyInstaller (onedir, windowed, bundles config.json)' {
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
Invoke-Step "Inno Setup ($iscc)" { & $iscc 'installer\FileOrganizer.iss' }

$installer = 'installer\Output\Setup-FileOrganizer.exe'
if (-not (Test-Path -LiteralPath $installer)) { throw "expected installer missing: $installer" }

# -- 3. Optional Authenticode signing -----------------------------------------
$pfx = $env:FILEORGANIZER_CERT_PFX
if ([string]::IsNullOrWhiteSpace($pfx) -or -not (Test-Path -LiteralPath $pfx)) {
    Write-Host "`nSkipping code signing: FILEORGANIZER_CERT_PFX is not set (unsigned dev build)." -ForegroundColor Yellow
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
    $password = $env:FILEORGANIZER_CERT_PASSWORD
    if ([string]::IsNullOrEmpty($password)) {
        $secure = Read-Host -Prompt 'Certificate password (not stored anywhere)' -AsSecureString
        $password = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
            [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
    }
    foreach ($target in @('dist\FileOrganizer\FileOrganizer.exe', $installer)) {
        Write-Host "`nSigning $target ..." -ForegroundColor Cyan
        & $signtool sign /f $pfx /p $password /fd sha256 /tr http://timestamp.digicert.com /td sha256 $target
        if ($LASTEXITCODE -ne 0) { throw "signtool failed for $target (exit $LASTEXITCODE)" }
    }
    Write-Host '`nBoth the app exe and the installer are signed.' -ForegroundColor Green
}

Write-Host "`nBuild complete (unsigned unless a certificate was configured):" -ForegroundColor Green
Get-Item -LiteralPath 'dist\FileOrganizer\FileOrganizer.exe', $installer |
    Select-Object FullName, @{n = 'MB'; e = { [math]::Round($_.Length / 1MB, 1) } } |
    Format-Table -AutoSize | Out-String | Write-Host
