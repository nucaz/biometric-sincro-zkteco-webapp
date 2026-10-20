<#
.SYNOPSIS
  Instalador interactivo del despliegue con Docker (Windows), para
  servidor central (web + sync + Postgres) o agente remoto (puente hacia
  biométricos de una sede que la central no puede alcanzar directo).

.DESCRIPTION
  Pide SIEMPRE, por pantalla, los datos de conexión y credenciales (nunca
  asume valores por defecto en silencio) -- a propósito, para que cada
  instalación quede con sus propias claves y quede un registro de qué se
  ingresó. Al final escribe el archivo .env que usa Docker Compose y un
  .txt aparte con un resumen de todo lo instalado (ver advertencia de
  seguridad al final del script y en el propio archivo generado).

  Usa Read-Host normal (sin -AsSecureString) para las contraseñas: se
  probó en esta sesión que -AsSecureString se queda colgado para siempre
  si la entrada no viene de una consola interactiva de verdad (por
  ejemplo, si este script se llama desde otro proceso) -- y de todos
  modos install.ps1 del despliegue nativo (deploy\windows_server) ya
  recibe la contraseña del admin en texto plano por parámetro, así que
  esto no es menos seguro que lo que ya existe.

.EXAMPLE
  .\deploy\docker\install.ps1
#>

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$DockerDir = $PSScriptRoot
$MarkerFile = Join-Path $DockerDir ".deploy_mode"

function Assert-CommandExists($name, $hint) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "$name no está disponible en PATH. $hint"
    }
}

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

function Get-OrDefault($Map, [string]$Key, [string]$Default) {
    if ($Map.ContainsKey($Key) -and -not [string]::IsNullOrWhiteSpace($Map[$Key])) { return $Map[$Key] }
    return $Default
}

function Read-ExistingEnv([string]$Path) {
    $map = @{}
    if (Test-Path $Path) {
        foreach ($line in Get-Content $Path) {
            if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
                $map[$matches[1]] = $matches[2]
            }
        }
    }
    return $map
}

Write-Host "=== Instalador Docker - Asistencia biométrica ===" -ForegroundColor White
Write-Host ""

Assert-CommandExists "docker" "Instala Docker Desktop desde https://www.docker.com/products/docker-desktop/ y vuelve a correr este script."
docker compose version | Out-Null
if ($LASTEXITCODE -ne 0) { throw "'docker compose' no respondió. ¿Docker Desktop está corriendo?" }

Write-Host "¿Qué vas a instalar en esta máquina?" -ForegroundColor Cyan
Write-Host "  1) Servidor central (panel web + sincronización + base de datos)"
Write-Host "  2) Agente remoto (puente hacia biométricos de una sede, sin panel ni base propia)"
$modeChoice = ""
while ($modeChoice -notin @("1", "2")) {
    $modeChoice = Read-Host "Elige 1 o 2"
}
$Mode = if ($modeChoice -eq "1") { "central" } else { "agent" }
Set-Content -Path $MarkerFile -Value $Mode -Encoding ASCII
Write-Host ""

$IsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)

$InstallLog = [ordered]@{}
$InstallLog["Fecha de instalación"] = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
$InstallLog["Modo"] = if ($Mode -eq "central") { "Servidor central" } else { "Agente remoto" }
$InstallLog["Carpeta del repositorio"] = $RepoRoot.Path

if ($Mode -eq "central") {
    $EnvPath = Join-Path $RepoRoot ".env"
    $existing = Read-ExistingEnv $EnvPath

    Write-Host "--- Datos de la base de datos (PostgreSQL) ---" -ForegroundColor Cyan
    $PgUser = Read-WithDefault "Usuario de la base de datos" (Get-OrDefault $existing "POSTGRES_USER" "asistencia")
    $PgDb = Read-WithDefault "Nombre de la base de datos" (Get-OrDefault $existing "POSTGRES_DB" "asistencia")
    $PgPasswordInput = Read-Host "Contraseña de la base de datos (Enter para generar una automática)"
    $PgPassword = if ([string]::IsNullOrWhiteSpace($PgPasswordInput)) { New-RandomSecret } else { $PgPasswordInput.Trim() }

    Write-Host ""
    Write-Host "--- Datos del panel web ---" -ForegroundColor Cyan
    $WebPort = Read-WithDefault "Puerto donde se publica el panel" (Get-OrDefault $existing "WEB_PORT" "5000")
    $SecretKeyInput = Read-Host "SECRET_KEY para firmar sesiones (Enter para generar una automática)"
    $SecretKey = if ([string]::IsNullOrWhiteSpace($SecretKeyInput)) { New-RandomSecret } else { $SecretKeyInput.Trim() }

    Write-Host ""
    Write-Host "--- Sincronización automática de los biométricos ---" -ForegroundColor Cyan
    $SyncDailyAt = Read-WithDefault "Hora diaria de sincronización (HH:mm, fuera de horario laboral)" (Get-OrDefault $existing "SYNC_DAILY_AT" "23:00")

    Write-Host ""
    Write-Host "--- Agentes remotos (sedes detrás de otra VPN) ---" -ForegroundColor Cyan
    Write-Host "Si alguna sede va a conectar un agente remoto a esta base (ver" -ForegroundColor DarkGray
    Write-Host "deploy\docker\README.md), este puerto tiene que estar accesible por" -ForegroundColor DarkGray
    Write-Host "VPN. Si no sabés, dejalo con el valor por defecto -- no hace daño." -ForegroundColor DarkGray
    $PgPort = Read-WithDefault "Puerto de PostgreSQL expuesto" (Get-OrDefault $existing "POSTGRES_PORT" "5432")

    Write-Host ""
    Write-Host "--- Primera cuenta de super administrador del panel ---" -ForegroundColor Cyan
    $AdminUser = Read-WithDefault "Usuario administrador" "admin"
    $AdminPassword = Read-Required "Contraseña del administrador (elige una clave fuerte)"

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

    $InstallLog["Usuario de base de datos"] = $PgUser
    $InstallLog["Contraseña de base de datos"] = $PgPassword
    $InstallLog["Nombre de base de datos"] = $PgDb
    $InstallLog["Puerto del panel"] = $WebPort
    $InstallLog["Puerto de PostgreSQL expuesto"] = $PgPort
    $InstallLog["SECRET_KEY"] = $SecretKey
    $InstallLog["Hora de sincronización diaria"] = $SyncDailyAt
    $InstallLog["Usuario administrador del panel"] = $AdminUser
    $InstallLog["Contraseña del administrador del panel"] = $AdminPassword
    $InstallLog["Panel web"] = "http://localhost:$WebPort"

    Write-Host ""
    Write-Host "Levantando los contenedores (esto construye la imagen, puede tardar unos minutos)..." -ForegroundColor Cyan
    Push-Location $RepoRoot
    try {
        docker compose up -d --build
        if ($LASTEXITCODE -ne 0) { throw "docker compose up -d --build terminó con errores -- revisa el mensaje de arriba." }

        Write-Host "Esperando que la base de datos esté lista..." -ForegroundColor Cyan
        $ready = $false
        for ($i = 0; $i -lt 30; $i++) {
            docker compose exec -T db pg_isready -U $PgUser | Out-Null
            if ($LASTEXITCODE -eq 0) { $ready = $true; break }
            Start-Sleep -Seconds 2
        }
        if (-not $ready) { Write-Warning "La base de datos no respondió a tiempo -- revisa 'docker compose logs db' antes de seguir." }

        Write-Host "Creando la cuenta de super administrador '$AdminUser'..." -ForegroundColor Cyan
        docker compose exec -T web python -m central.create_admin $AdminUser $AdminPassword
        if ($LASTEXITCODE -ne 0) { Write-Warning "central.create_admin terminó con código $LASTEXITCODE -- puede que la cuenta ya existiera de una instalación anterior." }
    } finally {
        Pop-Location
    }

    $FirewallRuleName = "Asistencia - PostgreSQL (agentes remotos)"
    if ($IsAdmin) {
        Write-Host "Abriendo el puerto $PgPort en el Firewall de Windows (para agentes remotos)..." -ForegroundColor Cyan
        try {
            if (-not (Get-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue)) {
                New-NetFirewallRule -DisplayName $FirewallRuleName -Direction Inbound -Protocol TCP -LocalPort $PgPort -Action Allow | Out-Null
            }
            Write-Host "Regla de Firewall lista." -ForegroundColor Green
        } catch {
            Write-Warning "No se pudo crear la regla de Firewall automáticamente: $($_.Exception.Message). Si vas a usar agentes remotos, creala a mano (PowerShell como Administrador):"
            Write-Host "  New-NetFirewallRule -DisplayName '$FirewallRuleName' -Direction Inbound -Protocol TCP -LocalPort $PgPort -Action Allow" -ForegroundColor Yellow
        }
    } else {
        Write-Host "Esta consola no es de Administrador, así que no se pudo abrir el puerto $PgPort en el Firewall de Windows." -ForegroundColor Yellow
        Write-Host "Si vas a usar agentes remotos en otras sedes, corré esto en una PowerShell como Administrador:" -ForegroundColor Yellow
        Write-Host "  New-NetFirewallRule -DisplayName '$FirewallRuleName' -Direction Inbound -Protocol TCP -LocalPort $PgPort -Action Allow" -ForegroundColor Yellow
    }
} else {
    $EnvPath = Join-Path $DockerDir ".env"
    $existing = Read-ExistingEnv $EnvPath

    Write-Host "--- Identidad de este agente ---" -ForegroundColor Cyan
    Write-Host "Este nombre debe coincidir EXACTO con el 'Agente remoto' que se" -ForegroundColor DarkGray
    Write-Host "configure en Dispositivos, en el panel central, para cada equipo" -ForegroundColor DarkGray
    Write-Host "de esta sede." -ForegroundColor DarkGray
    $AgentName = Read-Required "Nombre de este agente (ej. sede-pueblo-libre)"

    Write-Host ""
    Write-Host "--- Conexión a la base de datos del servidor central ---" -ForegroundColor Cyan
    $CentralHost = Read-Required "IP o DNS del servidor central"
    $CentralPort = Read-WithDefault "Puerto de PostgreSQL en el servidor central" "5432"
    $CentralDb = Read-WithDefault "Nombre de la base de datos central" "asistencia"
    $CentralUser = Read-WithDefault "Usuario de la base de datos central" "asistencia"
    Write-Host "(Evita '@' y ':' en esta contraseña -- forman parte de la URL de conexión y la romperían. Las generadas automáticamente por este instalador nunca los usan.)" -ForegroundColor DarkGray
    $CentralPassword = Read-Required "Contraseña de la base de datos central (la misma que tiene el servidor central)"

    Write-Host ""
    Write-Host "--- Sincronización automática de los biométricos de esta sede ---" -ForegroundColor Cyan
    $SyncDailyAt = Read-WithDefault "Hora diaria de sincronización (HH:mm)" (Get-OrDefault $existing "SYNC_DAILY_AT" "23:00")

    $DatabaseUrl = "postgresql+psycopg2://${CentralUser}:${CentralPassword}@${CentralHost}:${CentralPort}/${CentralDb}"
    $EnvContent = @"
AGENT_NAME=$AgentName
DATABASE_URL=$DatabaseUrl
SYNC_DAILY_AT=$SyncDailyAt
SYNC_INTERVAL_MINUTES=
"@
    Set-Content -Path $EnvPath -Value $EnvContent -Encoding ASCII

    $InstallLog["Nombre del agente (AGENT_NAME)"] = $AgentName
    $InstallLog["Servidor central (IP/DNS)"] = $CentralHost
    $InstallLog["Puerto PostgreSQL central"] = $CentralPort
    $InstallLog["Base de datos central"] = $CentralDb
    $InstallLog["Usuario base de datos central"] = $CentralUser
    $InstallLog["Contraseña base de datos central"] = $CentralPassword
    $InstallLog["Hora de sincronización diaria"] = $SyncDailyAt

    Write-Host ""
    Write-Host "Levantando el contenedor del agente (esto construye la imagen, puede tardar unos minutos)..." -ForegroundColor Cyan
    Push-Location $RepoRoot
    try {
        docker compose -f "$DockerDir\docker-compose.agent.yml" --env-file $EnvPath up -d --build
        if ($LASTEXITCODE -ne 0) { throw "docker compose up -d --build terminó con errores -- revisa el mensaje de arriba." }
    } finally {
        Pop-Location
    }

    Write-Host ""
    Write-Host "Recuerda: en el panel central, edita cada dispositivo de esta sede" -ForegroundColor Yellow
    Write-Host "y pon '$AgentName' en el campo 'Agente remoto'." -ForegroundColor Yellow
}

$LogPath = Join-Path $DockerDir "instalacion_$(Get-Date -Format 'yyyyMMdd_HHmmss').txt"
$LogLines = @(
    "Resumen de instalación -- Asistencia biométrica (Docker)"
    "============================================================"
    "ADVERTENCIA: este archivo contiene contraseñas en texto plano."
    "Guárdalo en un lugar seguro (ej. un gestor de contraseñas) y"
    "luego BÓRRALO de esta carpeta -- no lo dejes junto al código."
    ""
)
foreach ($key in $InstallLog.Keys) {
    $LogLines += "$key`: $($InstallLog[$key])"
}
Set-Content -Path $LogPath -Value $LogLines -Encoding UTF8

Write-Host ""
Write-Host "=== Listo ===" -ForegroundColor Green
if ($Mode -eq "central") {
    Write-Host "Panel: http://localhost:$WebPort (o http://<IP-del-servidor>:$WebPort desde otra máquina)" -ForegroundColor Green
}
Write-Host "Resumen con todas las credenciales ingresadas: $LogPath" -ForegroundColor Green
Write-Host "Para iniciar/detener/reiniciar/diagnosticar más adelante, usa manage.ps1 en esta misma carpeta" -ForegroundColor DarkGray
Write-Host "(o los .bat de doble clic: AsistenciaDocker_Iniciar, _Detener, _Reiniciar, _Diagnostico, _Estado)." -ForegroundColor DarkGray
