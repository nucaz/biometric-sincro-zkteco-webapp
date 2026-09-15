<#
.SYNOPSIS
  Rebuilds the desktop app end-to-end: reads VERSION, compiles the .exe
  with PyInstaller, then wraps it into a signed-looking, versioned Windows
  installer with Inno Setup. This is the ONLY supported way to produce a
  new release -- run it after pulling the latest source, never hand-edit
  the compiled .exe.

.EXAMPLE
  .\deploy\windows_desktop\build.ps1
#>
Set-StrictMode -Off
# NOTE: deliberately NOT $ErrorActionPreference = "Stop" -- PyInstaller and
# ISCC write normal progress info to stderr, and Stop would abort this
# script on the first such line regardless of exit code. Every external
# call below is checked via $LASTEXITCODE instead.

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Venv = Join-Path $ProjectRoot "venv\Scripts"
$Python = Join-Path $Venv "python.exe"
$ISCC = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"

if (-not (Test-Path $Python)) {
    throw "venv not found at $Venv -- create it first: python -m venv venv; venv\Scripts\pip install -r requirements.txt pyinstaller"
}
if (-not (Test-Path $ISCC)) {
    throw "Inno Setup 6 not found at $ISCC -- install it from https://jrsoftware.org/isdl.php"
}

$Version = (Get-Content (Join-Path $ProjectRoot "VERSION") -Raw).Trim()
if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw "VERSION file must be X.Y.Z (got '$Version')"
}
Write-Host "Building version $Version" -ForegroundColor Cyan

# 1. Regenerate the exe's file-properties resource for this version.
$Parts = $Version.Split('.')
$VersionTuple = "($($Parts[0]), $($Parts[1]), $($Parts[2]), 0)"
$VersionInfoPath = Join-Path $PSScriptRoot "version_info.txt"
$VersionInfo = @"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=$VersionTuple,
    prodvers=$VersionTuple,
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0),
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          u'040904B0',
          [
            StringStruct(u'CompanyName', u'Juan Carlos Aguirre Alvarado - Infraestructura TI & Ciberseguridad Apps'),
            StringStruct(u'FileDescription', u'ZKTeco Attendance System'),
            StringStruct(u'FileVersion', u'$Version.0'),
            StringStruct(u'InternalName', u'ZKTecoAttendanceSystem'),
            StringStruct(u'LegalCopyright', u'Develop Juan Carlos Aguirre Alvarado'),
            StringStruct(u'OriginalFilename', u'ZKTecoAttendanceSystem.exe'),
            StringStruct(u'ProductName', u'ZKTeco Attendance System'),
            StringStruct(u'ProductVersion', u'$Version.0'),
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"@
Set-Content -Path $VersionInfoPath -Value $VersionInfo -Encoding UTF8
Write-Host "Wrote version_info.txt for $Version" -ForegroundColor DarkGray

# 2. PyInstaller: source -> standalone exe.
Push-Location $ProjectRoot
try {
    & $Python -m PyInstaller --noconfirm --clean "deploy/windows_desktop/attendance_gui.spec"
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}

# 3. Inno Setup: exe -> versioned Setup.exe with uninstaller.
$Output = Join-Path $ProjectRoot "dist_installer\ZKTecoAttendanceSystem_Setup_$Version.0.exe"
if (Test-Path $Output) {
    # Windows Defender briefly locks freshly-written exes for its on-access
    # scan -- delete the previous build first (with a short retry) so ISCC
    # doesn't fail trying to overwrite a file that's mid-scan.
    for ($i = 0; $i -lt 5; $i++) {
        try { Remove-Item $Output -Force -ErrorAction Stop; break }
        catch { Start-Sleep -Seconds 2 }
    }
}
& $ISCC "deploy\windows_desktop\installer.iss" | Out-Host
if ($LASTEXITCODE -ne 0) { throw "Inno Setup compile failed (exit $LASTEXITCODE). If it's error 32 (file in use), Windows Defender is likely still scanning the previous build -- wait a few seconds and re-run this script." }

if (Test-Path $Output) {
    Write-Host "`nDone: $Output" -ForegroundColor Green
} else {
    Write-Warning "Expected output not found at $Output -- check the Inno Setup log above."
}
