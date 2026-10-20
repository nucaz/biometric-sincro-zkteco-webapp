<#
.SYNOPSIS
  Migra el servidor CENTRAL de SQLite a PostgreSQL, TODO nativo en
  Windows -- sin Docker, pensado para un servidor (o una VM) sin
  virtualización habilitada. El panel sigue corriendo exactamente igual
  que hoy (Tareas Programadas, deploy\windows_server\install.ps1), solo
  que contra PostgreSQL en vez de SQLite.

.DESCRIPTION
  Requisito previo (manual, una sola vez): tener PostgreSQL para Windows
  ya instalado -- descargalo de https://www.postgresql.org/download/windows/,
  corré el instalador, y ANOTÁ la contraseña que le pongas al usuario
  "postgres" durante la instalación (este script la necesita).

  Pasos, en orden:
    1. Busca psql.exe (confirma que PostgreSQL ya está instalado).
    2. Pide confirmación explícita (esto toca datos de producción).
    3. Pide la contraseña del superusuario "postgres" y los datos de la
       base/usuario de la app (SIEMPRE, nunca valores por defecto en
       silencio) -- crea esa base y ese usuario si no existen todavía.
    4. Detiene las tareas programadas nativas y respalda el SQLite real
       con fecha, antes de tocar nada.
    5. Corre central/migrate_sqlite_to_postgres.py contra esa copia.
    6. Si la migración salió bien, reusa deploy\windows_server\install.ps1
       (el instalador nativo de siempre) con -DatabaseUrl apuntando a
       PostgreSQL -- deja el panel corriendo exactamente como ya lo
       conocés, solo que con la base nueva.
    7. Abre el puerto de PostgreSQL en el Firewall de Windows (para
       agentes remotos de otras sedes).

  Necesita una PowerShell de Administrador.

.PARAMETER InstallDir
  Carpeta de la instalación nativa existente (default: C:\Asistencia).

.EXAMPLE
  .\deploy\windows_server\migrar_a_postgresql.ps1
#>
param(
    [string]$InstallDir = "C:\Asistencia"
)

$ErrorActionPreference = "Stop"

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

Write-Host "=== Migración del servidor central: SQLite -> PostgreSQL (sin Docker) ===" -ForegroundColor White
Write-Host ""

$IsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
if (-not $IsAdmin) {
    Write-Warning "Esta PowerShell no es de Administrador -- hace falta para detener las tareas programadas y reinstalar el panel al final. Cerrá esta ventana y volvé a abrirla con 'Ejecutar como administrador'."
    exit 1
}

Write-Host "Buscando PostgreSQL instalado en esta máquina..." -ForegroundColor Cyan
$PsqlExe = Get-ChildItem -Path "C:\Program Files\PostgreSQL\*\bin\psql.exe" -ErrorAction SilentlyContinue |
    Sort-Object -Property DirectoryName -Descending | Select-Object -First 1 -ExpandProperty FullName
if (-not $PsqlExe) {
    $cmd = Get-Command psql -ErrorAction SilentlyContinue
    if ($cmd) { $PsqlExe = $cmd.Source }
}
if (-not $PsqlExe) {
    Write-Host "No se encontró PostgreSQL instalado en esta máquina." -ForegroundColor Red
    Write-Host ""
    Write-Host "Paso previo (manual, una sola vez):" -ForegroundColor Yellow
    Write-Host "  1) Descargá el instalador de https://www.postgresql.org/download/windows/" -ForegroundColor Yellow
    Write-Host "  2) Corré el instalador (dejá el puerto 5432 por defecto)." -ForegroundColor Yellow
    Write-Host "  3) Cuando te pida una contraseña para el usuario 'postgres', ANOTALA -- este script la necesita." -ForegroundColor Yellow
    Write-Host "  4) Volvé a correr este mismo script." -ForegroundColor Yellow
    exit 1
}
Write-Host "Encontrado: $PsqlExe" -ForegroundColor Green

$SqlitePath = Join-Path $InstallDir "central\attendance.db"
if (-not (Test-Path $SqlitePath)) {
    Write-Host "No se encontró $SqlitePath." -ForegroundColor Yellow
    $SqlitePath = Read-Required "Ruta completa al archivo attendance.db real"
    if (-not (Test-Path $SqlitePath)) { throw "No existe ese archivo: $SqlitePath" }
}

Write-Host ""
Write-Host "Esto va a:" -ForegroundColor Yellow
Write-Host "  1) DETENER el panel y la sincronización ahora mismo." -ForegroundColor Yellow
Write-Host "  2) Copiar $SqlitePath a un respaldo antes de tocar nada." -ForegroundColor Yellow
Write-Host "  3) Crear la base de datos en PostgreSQL y traer TODOS los datos reales." -ForegroundColor Yellow
Write-Host "  4) Dejar el panel corriendo de nuevo, igual que siempre, contra PostgreSQL." -ForegroundColor Yellow
$confirm = Read-Host "`n¿Continuar? (escribí 'si' para confirmar)"
if ($confirm -notin @("si", "sí", "s")) {
    Write-Host "Cancelado -- no se tocó nada." -ForegroundColor Cyan
    exit 0
}

Write-Host "`n--- Datos de PostgreSQL ---" -ForegroundColor Cyan
$PgSuperPassword = Read-Required "Contraseña del usuario 'postgres' (la que pusiste al instalar PostgreSQL)"
$PgPort = Read-WithDefault "Puerto donde corre PostgreSQL" "5432"
$PgUser = Read-WithDefault "Usuario para la app (se crea si no existe)" "asistencia"
$PgDb = Read-WithDefault "Nombre de la base de datos (se crea si no existe)" "asistencia"
$PgPasswordInput = Read-Host "Contraseña para ese usuario (Enter para generar una automática)"
$PgPassword = if ([string]::IsNullOrWhiteSpace($PgPasswordInput)) { New-RandomSecret } else { $PgPasswordInput.Trim() }

function Invoke-Psql([string]$Sql) {
    # ON_ERROR_STOP + revisar $LASTEXITCODE, NUNCA el texto del error --
    # PostgreSQL devuelve el mensaje en el idioma del sistema (en este
    # Windows en español: "el rol «x» ya existe", no "already exists" en
    # inglés) -- detectarlo por texto fallaba en silencio. Por eso
    # Test-PgRoleExists/Test-PgDatabaseExists de abajo CONSULTAN antes de
    # crear, en vez de crear y adivinar el error después.
    $env:PGPASSWORD = $PgSuperPassword
    try {
        $output = & $PsqlExe -U postgres -h localhost -p $PgPort -v "ON_ERROR_STOP=1" -c $Sql 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "psql falló: $output"
        }
    } finally {
        Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
    }
}

function Test-PgRoleExists([string]$RoleName) {
    $env:PGPASSWORD = $PgSuperPassword
    try {
        $result = & $PsqlExe -U postgres -h localhost -p $PgPort -t -A -c "SELECT 1 FROM pg_roles WHERE rolname='$RoleName';" 2>&1
        return ($LASTEXITCODE -eq 0 -and $result -match "^1$")
    } finally {
        Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
    }
}

function Test-PgDatabaseExists([string]$DbName) {
    $env:PGPASSWORD = $PgSuperPassword
    try {
        $result = & $PsqlExe -U postgres -h localhost -p $PgPort -t -A -c "SELECT 1 FROM pg_database WHERE datname='$DbName';" 2>&1
        return ($LASTEXITCODE -eq 0 -and $result -match "^1$")
    } finally {
        Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
    }
}

Write-Host "`nCreando usuario y base de datos en PostgreSQL (si no existen)..." -ForegroundColor Cyan
if (Test-PgRoleExists $PgUser) {
    # Sincroniza la contraseña real en PostgreSQL con la que se acaba de
    # ingresar/generar en ESTA corrida -- si se dejara la existente sin
    # tocar, $PgPassword (lo que se usa más abajo para armar el
    # DATABASE_URL) casi nunca iba a coincidir con la de una corrida
    # anterior, y la conexión fallaba por contraseña incorrecta (visto
    # en esta sesión: psycopg2 ni siquiera llega a mostrar "contraseña
    # incorrecta" con claridad, porque el mensaje de error de PostgreSQL
    # viene en español y no se puede decodificar como UTF-8 -- aparece
    # como UnicodeDecodeError, mucho más confuso).
    Write-Host "  Usuario '$PgUser' ya existe -- actualizando su contraseña a la que acabás de ingresar." -ForegroundColor DarkGray
    Invoke-Psql "ALTER USER $PgUser WITH PASSWORD '$PgPassword';"
} else {
    Invoke-Psql "CREATE USER $PgUser WITH PASSWORD '$PgPassword';"
}
if (Test-PgDatabaseExists $PgDb) {
    Write-Host "  Base de datos '$PgDb' ya existe -- se deja igual." -ForegroundColor DarkGray
} else {
    Invoke-Psql "CREATE DATABASE $PgDb OWNER $PgUser;"
}
Write-Host "Listo." -ForegroundColor Green

Write-Host "`nDeteniendo las tareas programadas..." -ForegroundColor Cyan
Stop-ScheduledTask -TaskName "AsistenciaWeb" -ErrorAction SilentlyContinue
Stop-ScheduledTask -TaskName "AsistenciaSync" -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Get-Process -Name "python" -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path.StartsWith($InstallDir, [System.StringComparison]::OrdinalIgnoreCase) } |
    Stop-Process -Force -ErrorAction SilentlyContinue
Write-Host "Tareas detenidas." -ForegroundColor Green

# Actualiza $InstallDir con el código de ESTE repo (el que ya hiciste
# "git pull" acá) ANTES de intentar migrar -- sin esto, migrate_sqlite_
# to_postgres.py podía no existir todavía en $InstallDir si la última
# vez que corriste install.ps1 ahí fue antes de que este script
# existiera. Mismos excludes que usa install.ps1 (nunca toca el .db real
# ni devices.json).
Write-Host "`nActualizando $InstallDir con el código más reciente..." -ForegroundColor Cyan
$SourceDir = Resolve-Path (Join-Path $PSScriptRoot "..\..")
robocopy $SourceDir $InstallDir /MIR /XD venv __pycache__ dist dist_installer build .git /XF *.db devices.json | Out-Null
Write-Host "Código actualizado." -ForegroundColor Green

$BackupDir = Join-Path $InstallDir "backups"
if (-not (Test-Path $BackupDir)) { New-Item -ItemType Directory -Path $BackupDir | Out-Null }
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$BackupPath = Join-Path $BackupDir "attendance_backup_$Timestamp.db"
Write-Host "`nCopiando respaldo a $BackupPath..." -ForegroundColor Cyan
Copy-Item -Path $SqlitePath -Destination $BackupPath
foreach ($suffix in @("-wal", "-shm")) {
    $companion = "$SqlitePath$suffix"
    if (Test-Path $companion) { Copy-Item -Path $companion -Destination "$BackupPath$suffix" }
}
Write-Host "Respaldo listo. GUARDALO -- no lo borres hasta confirmar que todo quedó bien." -ForegroundColor Green

$DatabaseUrl = "postgresql+psycopg2://${PgUser}:${PgPassword}@localhost:${PgPort}/${PgDb}"
$NativePython = Join-Path $InstallDir "venv\Scripts\python.exe"
if (-not (Test-Path $NativePython)) { throw "No se encontró $NativePython -- ¿está bien instalado el panel en $InstallDir?" }

Write-Host "`nInstalando/actualizando dependencias (por si requirements.txt cambió)..." -ForegroundColor Cyan
# Ruta ABSOLUTA a propósito -- una relativa ("central\requirements.txt")
# depende de que el directorio de trabajo del proceso de pip (heredado
# de PowerShell vía Push-Location) esté bien sincronizado, y eso no
# siempre pasa igual en toda sesión elevada (visto en esta sesión: pip
# no encontró el archivo con una ruta relativa, mientras que la llamada
# de más abajo con -m SÍ funcionó -- más seguro no depender de esto acá).
$RequirementsPath = Join-Path $InstallDir "central\requirements.txt"
& $NativePython -m pip install -q -r $RequirementsPath
if ($LASTEXITCODE -ne 0) { throw "pip install falló (código $LASTEXITCODE) -- revisá el mensaje de arriba antes de seguir." }

Write-Host "`nMigrando los datos reales (esto puede tardar si hay muchas marcaciones)..." -ForegroundColor Cyan
$env:DATABASE_URL = $DatabaseUrl
Push-Location $InstallDir
try {
    & $NativePython -m central.migrate_sqlite_to_postgres --sqlite $BackupPath --yes
    $MigrationExitCode = $LASTEXITCODE
} finally {
    Pop-Location
    Remove-Item Env:\DATABASE_URL -ErrorAction SilentlyContinue
}

if ($MigrationExitCode -ne 0) {
    Write-Host "`n=== La migración falló -- el panel sigue detenido, sin tocar ===" -ForegroundColor Red
    Write-Host "El respaldo está a salvo en $BackupPath. Revisá el error de arriba." -ForegroundColor Red
    Write-Host "Para volver a lo de antes mientras lo investigás:" -ForegroundColor Yellow
    Write-Host "  Start-ScheduledTask -TaskName AsistenciaWeb" -ForegroundColor Yellow
    Write-Host "  Start-ScheduledTask -TaskName AsistenciaSync" -ForegroundColor Yellow
    exit 1
}

Write-Host "`nMigración OK. Reinstalando el panel apuntado a PostgreSQL..." -ForegroundColor Cyan
& "$PSScriptRoot\install.ps1" -DatabaseUrl $DatabaseUrl -InstallDir $InstallDir

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

$LogPath = Join-Path $InstallDir "migracion_postgresql_$Timestamp.txt"
$LogLines = @(
    "Resumen de migración a PostgreSQL (sin Docker)"
    "============================================================"
    "ADVERTENCIA: este archivo contiene contraseñas en texto plano."
    "Guárdalo en un lugar seguro y luego BÓRRALO de esta carpeta."
    ""
    "Fecha: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    "Usuario de base de datos: $PgUser"
    "Contraseña de base de datos: $PgPassword"
    "Nombre de base de datos: $PgDb"
    "Puerto de PostgreSQL: $PgPort"
    "Respaldo del SQLite original: $BackupPath"
)
Set-Content -Path $LogPath -Value $LogLines -Encoding UTF8

Write-Host "`n=== Listo ===" -ForegroundColor Green
Write-Host "Panel: http://localhost:5000 -- entrá con las MISMAS cuentas de siempre." -ForegroundColor Green
Write-Host "Resumen con las credenciales: $LogPath" -ForegroundColor Green
Write-Host "Respaldo del SQLite original: $BackupPath -- conservalo hasta estar seguro." -ForegroundColor Cyan
