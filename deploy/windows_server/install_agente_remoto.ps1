<#
.SYNOPSIS
  Instala el AGENTE REMOTO (central/remote_agent.py) en una sede cuyos
  biométricos el servidor central no puede alcanzar directo, SIN Docker
  -- Python + Tarea Programada de Windows, igual que el panel central
  nativo (deploy\windows_server\install.ps1). Pensado para una PC sin
  virtualización habilitada en BIOS, donde Docker Desktop no arranca.

.DESCRIPTION
  El agente remoto es un script de Python puro (no necesita Docker para
  nada): se conecta a los biométricos de ESTA sede por la LAN local, y al
  servidor central por la MISMA conexión de base de datos que ya usa el
  resto de la app (PostgreSQL por VPN). Corre como una Tarea Programada
  más, exactamente como ya corren AsistenciaWeb/AsistenciaSync en el
  servidor central.

  Pide SIEMPRE, por pantalla, el nombre del agente y los datos de
  conexión a la base central -- nunca instala con valores por defecto en
  silencio. Al final deja un archivo de texto con el resumen de todo lo
  ingresado.

.PARAMETER InstallDir
  Carpeta de instalación en esta PC (default: C:\AsistenciaAgente --
  deliberadamente distinta de C:\Asistencia, el default del panel
  central, para que las dos instalaciones nunca convivan en la misma
  ruta si alguna vez se instalan ambas en la misma máquina).

.EXAMPLE
  .\deploy\windows_server\install_agente_remoto.ps1

.NOTES
  Corré esto desde una PowerShell elevada ("Ejecutar como
  Administrador") -- la app se prepara igual sin elevar, pero registrar
  la Tarea Programada (lo que de verdad deja el agente corriendo) va a
  fallar al final.
#>
param(
    [string]$InstallDir = "C:\AsistenciaAgente"
)

$ErrorActionPreference = "Continue"

function Assert-CommandExists($name, $hint) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "$name no está disponible en PATH. $hint"
    }
}

function Assert-RealPython {
    # Windows pone un "alias de ejecución de aplicaciones" en PATH
    # (%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe) que Get-Command
    # encuentra igual que un Python real -- pero al correrlo solo abre
    # la Microsoft Store y no hace nada. Visto en esta sesión: pasó el
    # chequeo de "¿existe el comando?", pero "python -m venv venv" no
    # creó nada, y el resto del instalador siguió adelante sin darse
    # cuenta, hasta terminar registrando una Tarea Programada que apunta
    # a un venv\Scripts\python.exe que nunca existió. Por eso acá no
    # alcanza con "¿existe el comando?", hay que confirmar que de
    # verdad ejecuta código.
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw "python no está disponible en PATH. Instalá Python 3.10+ desde https://www.python.org/downloads/windows/ (marcá 'Add python.exe to PATH') y volvé a correr este script."
    }
    $versionOutput = & python --version 2>&1
    if ($LASTEXITCODE -ne 0 -or $versionOutput -notmatch "^Python \d") {
        throw "El 'python' que encuentra PATH no es una instalación real -- probablemente es el acceso directo de la Microsoft Store de Windows (salida: '$versionOutput'). Instalá Python 3.10+ de verdad desde https://www.python.org/downloads/windows/ (marcá 'Add python.exe to PATH'). Si ya lo instalaste y seguís viendo esto, desactivá el alias en Configuración > Aplicaciones > Configuración avanzada de aplicaciones > Alias de ejecución de aplicaciones (apagá 'python.exe' y 'python3.exe') y volvé a abrir la consola."
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

$IsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
if (-not $IsAdmin) {
    Write-Warning "No estás en una PowerShell elevada. La app se va a preparar igual, pero registrar la Tarea Programada (lo que de verdad deja el agente corriendo) va a fallar al final. Vuelve a correr este script como Administrador para completarlo."
}

Assert-RealPython

Write-Host "=== Instalador del agente remoto (sin Docker) ===" -ForegroundColor White
Write-Host ""
Write-Host "Este nombre debe coincidir EXACTO con el 'Agente remoto' que se" -ForegroundColor DarkGray
Write-Host "configure en Dispositivos, en el panel central, para cada equipo" -ForegroundColor DarkGray
Write-Host "de esta sede." -ForegroundColor DarkGray
$AgentName = Read-Required "Nombre de este agente (ej. sede-pueblo-libre)"

Write-Host ""
Write-Host "--- Conexión a la base de datos del servidor central ---" -ForegroundColor Cyan
Write-Host "Es la contraseña del USUARIO DE LA APP (ej. 'asistencia'), NO la del" -ForegroundColor DarkGray
Write-Host "superusuario 'postgres' -- está en el servidor central, en" -ForegroundColor DarkGray
Write-Host "C:\Asistencia\migracion_postgresql_<fecha>.txt, línea 'Contraseña de base de datos'." -ForegroundColor DarkGray
$CentralHost = Read-Required "IP o DNS del servidor central"
$CentralPort = Read-WithDefault "Puerto de PostgreSQL en el servidor central" "5432"
$CentralDb = Read-WithDefault "Nombre de la base de datos central" "asistencia"
$CentralUser = Read-WithDefault "Usuario de la base de datos central" "asistencia"
$CentralPassword = Read-Required "Contraseña de ese usuario en la base de datos central"

Write-Host ""
Write-Host "--- Sincronización automática de los biométricos de esta sede ---" -ForegroundColor Cyan
$SyncDailyAt = Read-WithDefault "Hora diaria de sincronización (HH:mm)" "23:00"

Write-Host ""
Write-Host "--- Página de estado local (opcional) ---" -ForegroundColor Cyan
Write-Host "Una página de solo lectura en esta misma PC para confirmar que el agente" -ForegroundColor DarkGray
Write-Host "está vivo y si llega a los biométricos de esta sede, sin PowerShell ni VPN." -ForegroundColor DarkGray
$AgentStatusPort = Read-WithDefault "Puerto para la página de estado (vacío o 0 para desactivarla)" "5050"

# Codificar usuario/contraseña para la URL (RFC 3986) -- sin esto, un
# "@", ":" o "/" dentro de la contraseña (algo totalmente normal, y pasó
# de verdad en esta sesión: una contraseña con "@" partía la URL en el
# lugar equivocado) arma un DATABASE_URL roto en silencio, con un error
# de conexión después que no dice nada sobre la causa real.
$CentralUserEnc = [System.Uri]::EscapeDataString($CentralUser)
$CentralPasswordEnc = [System.Uri]::EscapeDataString($CentralPassword)
$DatabaseUrl = "postgresql+psycopg2://${CentralUserEnc}:${CentralPasswordEnc}@${CentralHost}:${CentralPort}/${CentralDb}"

$SourceDir = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Write-Host "`nCopiando la aplicación a $InstallDir..." -ForegroundColor Cyan
robocopy $SourceDir $InstallDir /MIR /XD venv __pycache__ dist dist_installer build .git /XF *.db devices.json | Out-Null
if (-not (Test-Path "$InstallDir\devices.json")) {
    Set-Content -Path "$InstallDir\devices.json" -Value "[]" -Encoding ASCII
}

Push-Location $InstallDir
try {
    if (-not (Test-Path "venv")) {
        Write-Host "Creando entorno virtual..." -ForegroundColor Cyan
        python -m venv venv
    }
    if (-not (Test-Path ".\venv\Scripts\python.exe")) {
        throw "No se creó .\venv\Scripts\python.exe -- la instalación de Python no quedó bien (ver el chequeo de arriba)."
    }
    Write-Host "Instalando dependencias..." -ForegroundColor Cyan
    & ".\venv\Scripts\python.exe" -m pip install --upgrade pip -q
    & ".\venv\Scripts\python.exe" -m pip install -q -r "central\requirements.txt"
    if ($LASTEXITCODE -ne 0) { throw "pip install falló (código $LASTEXITCODE) -- revisá el mensaje de arriba antes de seguir." }
} finally {
    Pop-Location
}

# Segunda capa de protección, antes de registrar la Tarea Programada --
# si por cualquier motivo el venv no quedó usable (no solo "python" roto,
# también antivirus bloqueando la copia, disco lleno, etc.), más vale
# parar acá con un mensaje claro que registrar una tarea apuntando a un
# ejecutable que no existe y decir "Listo" igual (pasó de verdad en esta
# sesión).
if (-not (Test-Path "$InstallDir\venv\Scripts\python.exe")) {
    throw "$InstallDir\venv\Scripts\python.exe no existe -- no se puede registrar la Tarea Programada. Revisá los mensajes de arriba antes de volver a intentar."
}

if ($IsAdmin) {
    try {
        [Environment]::SetEnvironmentVariable("AGENT_NAME", $AgentName, "Machine")
        [Environment]::SetEnvironmentVariable("DATABASE_URL", $DatabaseUrl, "Machine")
        [Environment]::SetEnvironmentVariable("SYNC_DAILY_AT", $SyncDailyAt, "Machine")
        [Environment]::SetEnvironmentVariable("AGENT_STATUS_PORT", $AgentStatusPort, "Machine")
        Write-Host "Variables de entorno configuradas a nivel de máquina." -ForegroundColor Cyan
    } catch {
        Write-Warning "No se pudieron guardar las variables de entorno a nivel de máquina: $($_.Exception.Message)"
    }
} else {
    Write-Host "Sin permisos de administrador: las variables de entorno no se guardan a nivel de máquina (la tarea programada las necesitará luego -- corre este script elevado)." -ForegroundColor Yellow
}

$LogPath = Join-Path $InstallDir "instalacion_$(Get-Date -Format 'yyyyMMdd_HHmmss').txt"
$LogLines = @(
    "Resumen de instalación -- Agente remoto (sin Docker)"
    "============================================================"
    "ADVERTENCIA: este archivo contiene una contraseña en texto plano."
    "Guárdalo en un lugar seguro y luego BÓRRALO de esta carpeta."
    ""
    "Fecha de instalación: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    "Nombre del agente (AGENT_NAME): $AgentName"
    "Servidor central (IP/DNS): $CentralHost"
    "Puerto PostgreSQL central: $CentralPort"
    "Base de datos central: $CentralDb"
    "Usuario base de datos central: $CentralUser"
    "Contraseña base de datos central: $CentralPassword"
    "Hora de sincronización diaria: $SyncDailyAt"
    "Puerto de la página de estado: $(if ($AgentStatusPort -and $AgentStatusPort -ne '0') { $AgentStatusPort } else { '(desactivada)' })"
    "Carpeta de instalación: $InstallDir"
)
Set-Content -Path $LogPath -Value $LogLines -Encoding UTF8

if (-not $IsAdmin) {
    Write-Warning "Deteniendo aquí: registrar la Tarea Programada necesita una PowerShell elevada. La app ya está lista en $InstallDir -- vuelve a correr este mismo script como Administrador para dejar el agente corriendo."
    Write-Host "Resumen con los datos ingresados: $LogPath" -ForegroundColor Green
    exit 1
}

Write-Host "`nRegistrando la Tarea Programada..." -ForegroundColor Cyan
Stop-ScheduledTask -TaskName "AsistenciaAgenteRemoto" -ErrorAction SilentlyContinue
Get-Process -Name "python" -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path.StartsWith($InstallDir, [System.StringComparison]::OrdinalIgnoreCase) } |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

$AgentAction = New-ScheduledTaskAction -Execute "$InstallDir\venv\Scripts\python.exe" `
    -Argument "-m central.remote_agent" -WorkingDirectory $InstallDir
$AgentTrigger = New-ScheduledTaskTrigger -AtStartup
$AgentSettings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Days 0)
Register-ScheduledTask -TaskName "AsistenciaAgenteRemoto" -Action $AgentAction -Trigger $AgentTrigger -Settings $AgentSettings `
    -User "SYSTEM" -RunLevel Highest -Force | Out-Null

Write-Host "Iniciando el agente..." -ForegroundColor Cyan
Start-ScheduledTask -TaskName "AsistenciaAgenteRemoto"

if ($AgentStatusPort -and $AgentStatusPort -ne "0") {
    Write-Host "`nAbriendo el puerto $AgentStatusPort en el Firewall de Windows (página de estado)..." -ForegroundColor Cyan
    $FirewallRuleName = "Asistencia - Agente remoto (página de estado)"
    try {
        if (-not (Get-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue)) {
            New-NetFirewallRule -DisplayName $FirewallRuleName -Direction Inbound -Protocol TCP -LocalPort $AgentStatusPort -Action Allow | Out-Null
        }
        Write-Host "Regla de Firewall lista." -ForegroundColor Green
    } catch {
        Write-Warning "No se pudo crear la regla de Firewall automáticamente: $($_.Exception.Message)"
    }
}

Write-Host "`n=== Listo ===" -ForegroundColor Green
Write-Host "El agente '$AgentName' está corriendo como Tarea Programada." -ForegroundColor Green
if ($AgentStatusPort -and $AgentStatusPort -ne "0") {
    Write-Host "Página de estado (en esta red local): http://localhost:$AgentStatusPort" -ForegroundColor Green
}
Write-Host "Resumen con los datos ingresados: $LogPath" -ForegroundColor Green
Write-Host "`nRecordá: en el panel central, editá cada dispositivo de esta sede" -ForegroundColor Yellow
Write-Host "y poné '$AgentName' en el campo 'Agente remoto'." -ForegroundColor Yellow
Write-Host "`nVer estado:    Get-ScheduledTask -TaskName AsistenciaAgenteRemoto"
Write-Host "Gestión diaria: deploy\windows_server\agente_remoto_servicio.ps1 (o los .bat de doble clic)"
