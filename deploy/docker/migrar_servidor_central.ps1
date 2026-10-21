<#
.SYNOPSIS
  Migra el servidor CENTRAL de la instalación nativa de Windows (SQLite)
  al despliegue con Docker (PostgreSQL), trayendo los datos reales --
  empleados, marcaciones, usuarios del panel, horarios, todo.

.DESCRIPTION
  Pasos, en orden:
    1. Pide confirmación explícita (esto toca datos de producción).
    2. Detiene las tareas programadas nativas (AsistenciaWeb/AsistenciaSync)
       -- para que nada siga escribiendo en el SQLite mientras se migra.
    3. Hace una copia de respaldo del archivo SQLite real antes de tocar
       nada.
    4. Pide los datos de conexión de PostgreSQL (SIEMPRE, igual que
       install.ps1) y levanta SOLO el contenedor de base de datos.
    5. Corre central/migrate_sqlite_to_postgres.py contra esa copia --
       trae empleados, marcaciones, usuarios reales, todo. NO crea una
       cuenta de administrador nueva (los admins reales ya vienen
       migrados en la tabla de usuarios).
    6. Si la migración salió bien, recién ahí levanta el panel completo
       (web + sync) y trata de abrir el puerto de PostgreSQL en el
       Firewall de Windows (para agentes remotos).
    7. Dice claramente cómo volver atrás si algo se ve mal: las tareas
       programadas nativas siguen existiendo, solo están detenidas.

  Necesita una PowerShell de Administrador (detiene tareas programadas
  registradas como SYSTEM).

.PARAMETER NativeInstallDir
  Carpeta de la instalación nativa de Windows (default: C:\Asistencia,
  el mismo default que deploy\windows_server\install.ps1).

.EXAMPLE
  .\deploy\docker\migrar_servidor_central.ps1
#>
param(
    [string]$NativeInstallDir = "C:\Asistencia"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$DockerDir = $PSScriptRoot
$MarkerFile = Join-Path $DockerDir ".deploy_mode"
$EnvPath = Join-Path $RepoRoot ".env"

function Read-WithDefault([string]$Prompt, [string]$Default) {
    $suffix = if ($Default) { " [$Default]" } else { "" }
    $value = Read-Host "$Prompt$suffix"
    if ([string]::IsNullOrWhiteSpace($value)) { return $Default }
    return $value.Trim()
}

function Read-Required([string]$Prompt) {
    while ($true) {
        $value = Read-Host $Prompt
        if (-not [string]::IsNullOrWhiteSpace($value)) { return $value.Trim() }
        Write-Host "Este dato es obligatorio, no puede quedar en blanco." -ForegroundColor Yellow
    }
}

function New-RandomSecret {
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return [System.Convert]::ToBase64String($bytes)
}

Write-Host "=== Migración del servidor central: SQLite nativo -> Docker/PostgreSQL ===" -ForegroundColor White
Write-Host ""

$IsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
if (-not $IsAdmin) {
    Write-Warning "Esta PowerShell no es de Administrador -- hace falta para detener las tareas programadas (AsistenciaWeb/AsistenciaSync corren como SYSTEM). Cerrá esta ventana y volvé a abrirla con 'Ejecutar como administrador'."
    exit 1
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "docker no está disponible en PATH. Instalá Docker Desktop y volvé a correr este script."
}
docker compose version | Out-Null
if ($LASTEXITCODE -ne 0) { throw "'docker compose' no respondió. ¿Docker Desktop está corriendo?" }

$SqlitePath = Join-Path $NativeInstallDir "central\attendance.db"
if (-not (Test-Path $SqlitePath)) {
    Write-Host "No se encontró $SqlitePath." -ForegroundColor Yellow
    $SqlitePath = Read-Required "Ruta completa al archivo attendance.db real"
    if (-not (Test-Path $SqlitePath)) { throw "No existe ese archivo: $SqlitePath" }
}

Write-Host ""
Write-Host "Esto va a:" -ForegroundColor Yellow
Write-Host "  1) DETENER el panel y la sincronización nativos (AsistenciaWeb/AsistenciaSync) ahora mismo." -ForegroundColor Yellow
Write-Host "  2) Copiar $SqlitePath a un respaldo antes de tocar nada." -ForegroundColor Yellow
Write-Host "  3) Traer TODOS los datos reales (empleados, marcaciones, usuarios, horarios) a PostgreSQL." -ForegroundColor Yellow
Write-Host "  4) Levantar el panel nuevo con Docker, ya con esos datos." -ForegroundColor Yellow
Write-Host "Las tareas programadas nativas NO se eliminan, solo se detienen -- se puede volver atrás reactivándolas." -ForegroundColor Yellow
$confirm = Read-Host "`n¿Continuar? (escribí 'si' para confirmar)"
if ($confirm -notin @("si", "sí", "s")) {
    Write-Host "Cancelado -- no se tocó nada." -ForegroundColor Cyan
    exit 0
}

Write-Host "`nDeteniendo las tareas programadas nativas..." -ForegroundColor Cyan
Stop-ScheduledTask -TaskName "AsistenciaWeb" -ErrorAction SilentlyContinue
Stop-ScheduledTask -TaskName "AsistenciaSync" -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Get-Process -Name "python" -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path.StartsWith($NativeInstallDir, [System.StringComparison]::OrdinalIgnoreCase) } |
    Stop-Process -Force -ErrorAction SilentlyContinue
Write-Host "Tareas nativas detenidas." -ForegroundColor Green

$BackupDir = Join-Path $NativeInstallDir "backups"
if (-not (Test-Path $BackupDir)) { New-Item -ItemType Directory -Path $BackupDir | Out-Null }
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$BackupPath = Join-Path $BackupDir "attendance_backup_$Timestamp.db"
Write-Host "`nCopiando respaldo a $BackupPath..." -ForegroundColor Cyan
Copy-Item -Path $SqlitePath -Destination $BackupPath
foreach ($suffix in @("-wal", "-shm")) {
    $companion = "$SqlitePath$suffix"
    if (Test-Path $companion) { Copy-Item -Path $companion -Destination "$BackupPath$suffix" }
}
Write-Host "Respaldo listo. GUARDALO -- no lo borres hasta confirmar que todo quedó bien en el panel nuevo." -ForegroundColor Green

$existing = @{}
if (Test-Path $EnvPath) {
    foreach ($line in Get-Content $EnvPath) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') { $existing[$matches[1]] = $matches[2] }
    }
}
function Get-OrDefault($Map, [string]$Key, [string]$Default) {
    if ($Map.ContainsKey($Key) -and -not [string]::IsNullOrWhiteSpace($Map[$Key])) { return $Map[$Key] }
    return $Default
}

Write-Host "`n--- Datos de la base de datos (PostgreSQL) ---" -ForegroundColor Cyan
$PgUser = Read-WithDefault "Usuario de la base de datos" (Get-OrDefault $existing "POSTGRES_USER" "asistencia")
$PgDb = Read-WithDefault "Nombre de la base de datos" (Get-OrDefault $existing "POSTGRES_DB" "asistencia")
$PgPasswordInput = Read-Host "Contraseña de la base de datos (Enter para generar una automática)"
$PgPassword = if ([string]::IsNullOrWhiteSpace($PgPasswordInput)) { New-RandomSecret } else { $PgPasswordInput.Trim() }
$PgPort = Read-WithDefault "Puerto de PostgreSQL expuesto (para agentes remotos)" (Get-OrDefault $existing "POSTGRES_PORT" "5432")

Write-Host "`n--- Datos del panel web ---" -ForegroundColor Cyan
$WebPort = Read-WithDefault "Puerto donde se publica el panel" (Get-OrDefault $existing "WEB_PORT" "5000")
$SecretKeyInput = Read-Host "SECRET_KEY para firmar sesiones (Enter para generar una automática)"
$SecretKey = if ([string]::IsNullOrWhiteSpace($SecretKeyInput)) { New-RandomSecret } else { $SecretKeyInput.Trim() }

Write-Host "`n--- Sincronización automática de los biométricos ---" -ForegroundColor Cyan
$SyncDailyAt = Read-WithDefault "Hora diaria de sincronización (HH:mm)" (Get-OrDefault $existing "SYNC_DAILY_AT" "23:00")

$EnvContent = @"
POSTGRES_USER=$PgUser
POSTGRES_PASSWORD=$PgPassword
POSTGRES_DB=$PgDb
POSTGRES_PORT=$PgPort
SECRET_KEY=$SecretKey
WEB_PORT=$WebPort
SYNC_DAILY_AT=$SyncDailyAt
SYNC_INTERVAL_MINUTES=
"@
Set-Content -Path $EnvPath -Value $EnvContent -Encoding ASCII
Set-Content -Path $MarkerFile -Value "central" -Encoding ASCII

Write-Host "`nLevantando solo la base de datos (todavía no el panel)..." -ForegroundColor Cyan
Push-Location $RepoRoot
try {
    docker compose up -d --build db
    if ($LASTEXITCODE -ne 0) { throw "docker compose up -d --build db terminó con errores." }

    Write-Host "Esperando que la base de datos esté lista..." -ForegroundColor Cyan
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        docker compose exec -T db pg_isready -U $PgUser | Out-Null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) { throw "La base de datos no respondió a tiempo -- revisá 'docker compose logs db'." }
} finally {
    Pop-Location
}

$NativePython = Join-Path $NativeInstallDir "venv\Scripts\python.exe"
if (-not (Test-Path $NativePython)) {
    Write-Warning "No se encontró $NativePython -- usando 'python' del PATH en su lugar."
    $NativePython = "python"
}
Write-Host "Verificando que psycopg2 esté instalado para la migración..." -ForegroundColor Cyan
& $NativePython -c "import psycopg2" 2>$null
if ($LASTEXITCODE -ne 0) {
    & $NativePython -m pip install -q psycopg2-binary
}

Write-Host "`nMigrando los datos reales (esto puede tardar si hay muchas marcaciones)..." -ForegroundColor Cyan
$PgUserEnc = [System.Uri]::EscapeDataString($PgUser)
$PgPasswordEnc = [System.Uri]::EscapeDataString($PgPassword)
$env:DATABASE_URL = "postgresql+psycopg2://${PgUserEnc}:${PgPasswordEnc}@localhost:${PgPort}/${PgDb}"
Push-Location $RepoRoot
try {
    & $NativePython -m central.migrate_sqlite_to_postgres --sqlite $BackupPath --yes
    $MigrationExitCode = $LASTEXITCODE
} finally {
    Pop-Location
    Remove-Item Env:\DATABASE_URL -ErrorAction SilentlyContinue
}

if ($MigrationExitCode -ne 0) {
    Write-Host "`n=== La migración falló -- NO se levantó el panel nuevo ===" -ForegroundColor Red
    Write-Host "El respaldo está a salvo en $BackupPath. Revisá el error de arriba." -ForegroundColor Red
    Write-Host "Para volver al sistema nativo mientras lo investigás:" -ForegroundColor Yellow
    Write-Host "  Start-ScheduledTask -TaskName AsistenciaWeb" -ForegroundColor Yellow
    Write-Host "  Start-ScheduledTask -TaskName AsistenciaSync" -ForegroundColor Yellow
    exit 1
}

Write-Host "`nMigración OK. Levantando el panel completo..." -ForegroundColor Cyan
Push-Location $RepoRoot
try {
    docker compose up -d --build
    if ($LASTEXITCODE -ne 0) { throw "docker compose up -d --build terminó con errores." }
} finally {
    Pop-Location
}

$FirewallRuleName = "Asistencia - PostgreSQL (agentes remotos)"
Write-Host "`nAbriendo el puerto $PgPort en el Firewall de Windows (para agentes remotos)..." -ForegroundColor Cyan
try {
    if (-not (Get-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName $FirewallRuleName -Direction Inbound -Protocol TCP -LocalPort $PgPort -Action Allow | Out-Null
    }
    Write-Host "Regla de Firewall lista." -ForegroundColor Green
} catch {
    Write-Warning "No se pudo crear la regla de Firewall automáticamente: $($_.Exception.Message)"
}

Write-Host "`n=== Listo ===" -ForegroundColor Green
Write-Host "Panel nuevo (Docker/PostgreSQL): http://localhost:$WebPort" -ForegroundColor Green
Write-Host "Entrá con las MISMAS cuentas de siempre (se migraron junto con todo lo demás)." -ForegroundColor Green
Write-Host "`nEl sistema nativo quedó DETENIDO pero no desinstalado -- las tareas" -ForegroundColor Cyan
Write-Host "programadas AsistenciaWeb/AsistenciaSync siguen registradas. Si algo no" -ForegroundColor Cyan
Write-Host "se ve bien en el panel nuevo, podés volver atrás:" -ForegroundColor Cyan
Write-Host "  docker compose -f `"$RepoRoot\docker-compose.yml`" down" -ForegroundColor Yellow
Write-Host "  Start-ScheduledTask -TaskName AsistenciaWeb" -ForegroundColor Yellow
Write-Host "  Start-ScheduledTask -TaskName AsistenciaSync" -ForegroundColor Yellow
Write-Host "`nRespaldo del SQLite original: $BackupPath -- conservalo hasta estar seguro." -ForegroundColor Cyan
Write-Host "Gestión diaria de acá en adelante: deploy\docker\manage.ps1 (o los .bat de doble clic)." -ForegroundColor DarkGray
