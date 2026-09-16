<#
.SYNOPSIS
  Installs the central attendance service (Flask app + periodic sync) on
  a Windows Server: Python venv under C:\Asistencia, a waitress-served
  web app and a sync job, both run via Task Scheduler (no third-party
  service wrapper needed -- just what ships with Windows).

.PARAMETER DatabaseUrl
  SQLAlchemy connection string. Defaults to a local SQLite file, which
  needs nothing else installed. Point it at PostgreSQL/MySQL if you have
  one already running (this script does not install a DB *server* on
  Windows -- see deploy/windows_server/README.md).

.PARAMETER AdminUser / AdminPassword
  If given, creates the first super-admin account non-interactively.

.EXAMPLE
  .\deploy\windows_server\install.ps1 -AdminUser admin -AdminPassword "clave-fuerte"

.NOTES
  Run this from an elevated ("Run as Administrator") PowerShell. Without
  elevation it still sets up the app and the database, but registering
  the scheduled tasks (the actual running service) will fail -- you'll
  get a clear message telling you to re-run elevated.
#>
param(
    [string]$DatabaseUrl = "",
    [string]$AdminUser = "",
    [string]$AdminPassword = "",
    [string]$InstallDir = "C:\Asistencia"
)

$ErrorActionPreference = "Continue"  # native commands log to stderr; check exit codes explicitly instead

function Assert-CommandExists($name, $hint) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "$name no está disponible en PATH. $hint"
    }
}

$IsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
if (-not $IsAdmin) {
    Write-Warning "No estás en una PowerShell elevada. La app y la base de datos se van a preparar igual, pero registrar las tareas programadas (lo que de verdad deja el servicio corriendo) va a fallar al final. Vuelve a correr este script como Administrador para completarlo."
}

Assert-CommandExists "python" "Instala Python 3.10+ desde https://www.python.org/downloads/windows/ (marca 'Add python.exe to PATH') y vuelve a correr este script."

$SourceDir = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Write-Host "Copiando la aplicación a $InstallDir..." -ForegroundColor Cyan
# devices.json is excluded on purpose: it's the developer's own local
# device list (real IPs/serials), never something to ship to a server.
robocopy $SourceDir $InstallDir /MIR /XD venv __pycache__ dist dist_installer build .git /XF *.db devices.json | Out-Null
if (-not (Test-Path "$InstallDir\devices.json")) {
    # -Encoding UTF8 in Windows PowerShell 5.1 writes a BOM, which Python's
    # default-encoding file reads then choke on ("Expecting value" at
    # char 0) -- ASCII is fine here since the content is just "[]".
    Set-Content -Path "$InstallDir\devices.json" -Value "[]" -Encoding ASCII
}

Push-Location $InstallDir
try {
    if (-not (Test-Path "venv")) {
        Write-Host "Creando entorno virtual..." -ForegroundColor Cyan
        python -m venv venv
    }
    Write-Host "Instalando dependencias..." -ForegroundColor Cyan
    # python -m pip, not pip.exe directly -- pip.exe can't reliably upgrade
    # itself on Windows (it's the file it's currently running from).
    & ".\venv\Scripts\python.exe" -m pip install --upgrade pip -q
    & ".\venv\Scripts\python.exe" -m pip install -q -r "central\requirements.txt"

    # Reuse the existing SECRET_KEY on updates -- regenerating it on every
    # run would silently invalidate every logged-in session (Flask signs
    # the session cookie with it) each time this script re-runs.
    $ExistingSecretKey = [Environment]::GetEnvironmentVariable("SECRET_KEY", "Machine")
    if ($ExistingSecretKey) {
        $SecretKey = $ExistingSecretKey
        Write-Host "Reutilizando SECRET_KEY existente (no se cierran las sesiones activas)." -ForegroundColor DarkGray
    } else {
        $RngBytes = New-Object byte[] 32
        [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($RngBytes)
        $SecretKey = [System.Convert]::ToBase64String($RngBytes)
    }

    # Machine-level env vars are what the scheduled task (running as
    # SYSTEM, its own separate process) will read. They need admin to
    # write -- if that fails, don't let it take seed_devices/create_admin
    # down with it: those matter more and work fine without this.
    if ($IsAdmin) {
        try {
            if ($DatabaseUrl) {
                [Environment]::SetEnvironmentVariable("DATABASE_URL", $DatabaseUrl, "Machine")
            }
            [Environment]::SetEnvironmentVariable("SECRET_KEY", $SecretKey, "Machine")
            Write-Host "Variables de entorno configuradas a nivel de máquina." -ForegroundColor Cyan
        } catch {
            Write-Warning "No se pudieron guardar las variables de entorno a nivel de máquina: $($_.Exception.Message)"
        }
    } else {
        Write-Host "Sin permisos de administrador: las variables de entorno no se guardan a nivel de máquina (la tarea programada las necesitará luego -- corre este script elevado)." -ForegroundColor Yellow
    }
    if (-not $DatabaseUrl) {
        Write-Host "Sin -DatabaseUrl: usando SQLite local (central\attendance.db)." -ForegroundColor Yellow
    }

    Write-Host "Inicializando base de datos..." -ForegroundColor Cyan
    if ($DatabaseUrl) { $env:DATABASE_URL = $DatabaseUrl }
    $env:SECRET_KEY = $SecretKey
    & ".\venv\Scripts\python.exe" -m central.seed_devices
    if ($LASTEXITCODE -ne 0) { Write-Warning "central.seed_devices terminó con código $LASTEXITCODE -- revisa el mensaje de arriba." }

    if ($AdminUser -and $AdminPassword) {
        Write-Host "Creando cuenta de super administrador '$AdminUser'..." -ForegroundColor Cyan
        & ".\venv\Scripts\python.exe" -m central.create_admin $AdminUser $AdminPassword
        if ($LASTEXITCODE -ne 0) { Write-Warning "central.create_admin terminó con código $LASTEXITCODE -- revisa el mensaje de arriba." }
    } else {
        Write-Host "No diste -AdminUser/-AdminPassword. Crea la primera cuenta con:" -ForegroundColor Yellow
        Write-Host "  $InstallDir\venv\Scripts\python.exe -m central.create_admin admin TU_CLAVE"
    }
} finally {
    Pop-Location
}

if (-not $IsAdmin) {
    Write-Warning "Deteniendo aquí: registrar las tareas programadas necesita una PowerShell elevada. La app y la base de datos ya están listas en $InstallDir -- vuelve a correr este mismo script como Administrador para dejar el servicio corriendo."
    exit 1
}

Write-Host "Registrando tareas programadas..." -ForegroundColor Cyan

$WebAction = New-ScheduledTaskAction -Execute "$InstallDir\venv\Scripts\python.exe" `
    -Argument "-m waitress --host=0.0.0.0 --port=5000 central.webapp:app" -WorkingDirectory $InstallDir
$WebTrigger = New-ScheduledTaskTrigger -AtStartup
$WebSettings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Days 0)
Register-ScheduledTask -TaskName "AsistenciaWeb" -Action $WebAction -Trigger $WebTrigger -Settings $WebSettings `
    -User "SYSTEM" -RunLevel Highest -Force | Out-Null

$SyncAction = New-ScheduledTaskAction -Execute "$InstallDir\venv\Scripts\python.exe" `
    -Argument "-m central.sync" -WorkingDirectory $InstallDir
$SyncTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 15)
$SyncTrigger.Repetition.Duration = ""  # empty string = repeat indefinitely (Task Scheduler has no direct "forever" option)
Register-ScheduledTask -TaskName "AsistenciaSync" -Action $SyncAction -Trigger $SyncTrigger `
    -User "SYSTEM" -RunLevel Highest -Force | Out-Null

Write-Host "Iniciando el panel web..." -ForegroundColor Cyan
Start-ScheduledTask -TaskName "AsistenciaWeb"

Write-Host "`nListo. Panel: http://localhost:5000 (o http://<IP-del-servidor>:5000 desde otra máquina)" -ForegroundColor Green
Write-Host "Ver tareas:    Get-ScheduledTask -TaskName Asistencia*"
Write-Host "Detener web:   Stop-ScheduledTask -TaskName AsistenciaWeb"
Write-Host "Sync manual:   $InstallDir\venv\Scripts\python.exe -m central.sync"
