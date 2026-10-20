<#
.SYNOPSIS
  Interruptor de emergencia para el agente remoto nativo (sin Docker):
  inicia, detiene, reinicia, muestra estado o diagnostica la Tarea
  Programada "AsistenciaAgenteRemoto" que install_agente_remoto.ps1
  registró.

  No lo llames directo si preferís los botones de doble clic:
    AsistenciaAgenteRemoto_Iniciar.bat
    AsistenciaAgenteRemoto_Detener.bat
    AsistenciaAgenteRemoto_Reiniciar.bat
    AsistenciaAgenteRemoto_Estado.bat
    AsistenciaAgenteRemoto_Diagnostico.bat

.PARAMETER Action
  Start | Stop | Restart | Status | Diagnose (por defecto: Status)

.EXAMPLE
  .\deploy\windows_server\agente_remoto_servicio.ps1 -Action Restart
#>
param(
    [ValidateSet("Start", "Stop", "Restart", "Status", "Diagnose")]
    [string]$Action = "Status",
    [string]$InstallDir = "C:\AsistenciaAgente"
)

$TaskName = "AsistenciaAgenteRemoto"

function Stop-LingeringPython {
    Get-Process -Name "python" -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and $_.Path.StartsWith($InstallDir, [System.StringComparison]::OrdinalIgnoreCase) } |
        Stop-Process -Force -ErrorAction SilentlyContinue
}

$IsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
if (-not $IsAdmin -and $Action -notin @("Status", "Diagnose")) {
    Write-Warning "Esta acción ($Action) necesita PowerShell como Administrador. Cerrá esta ventana y volvé a abrirla con 'Ejecutar como administrador', o usá el .bat correspondiente (ya pide permisos solo)."
    exit 1
}

function Show-TaskStatus {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) {
        Write-Host "Tarea: $TaskName -- NO ENCONTRADA" -ForegroundColor Red
        Write-Host "  (¿Se corrió deploy\windows_server\install_agente_remoto.ps1 como Administrador?)" -ForegroundColor DarkGray
        return
    }
    $color = switch ($task.State) {
        "Running"  { "Green" }
        "Ready"    { "Yellow" }
        "Disabled" { "Red" }
        default    { "Gray" }
    }
    Write-Host "Tarea: " -NoNewline
    Write-Host "$TaskName" -ForegroundColor Cyan -NoNewline
    Write-Host "  ->  Estado: " -NoNewline
    Write-Host "$($task.State)" -ForegroundColor $color

    $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($info) {
        Write-Host "    Última ejecución:  $($info.LastRunTime)   Resultado: $($info.LastTaskResult)"
        Write-Host "    Próxima ejecución: $($info.NextRunTime)"
    }
}

switch ($Action) {
    "Start" {
        Write-Host "Iniciando la tarea '$TaskName'..." -ForegroundColor Cyan
        Start-ScheduledTask -TaskName $TaskName
        Start-Sleep -Seconds 2
    }
    "Stop" {
        Write-Host "Deteniendo la tarea '$TaskName'..." -ForegroundColor Cyan
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
        Stop-LingeringPython
    }
    "Restart" {
        Write-Host "Reiniciando la tarea '$TaskName'..." -ForegroundColor Cyan
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        Stop-LingeringPython
        Start-ScheduledTask -TaskName $TaskName
        Start-Sleep -Seconds 2
    }
}

if ($Action -ne "Diagnose") {
    Write-Host ""
    Write-Host "=== Estado actual del agente remoto ===" -ForegroundColor White
    Show-TaskStatus
    Write-Host ""
}

if ($Action -eq "Diagnose") {
    Write-Host "=== Diagnóstico del agente remoto ===" -ForegroundColor White
    Write-Host ""
    Show-TaskStatus
    Write-Host ""

    $EnvDatabaseUrl = [Environment]::GetEnvironmentVariable("DATABASE_URL", "Machine")
    $EnvAgentName = [Environment]::GetEnvironmentVariable("AGENT_NAME", "Machine")
    Write-Host "--- Variables de entorno ---" -ForegroundColor Cyan
    Write-Host "AGENT_NAME: $(if ($EnvAgentName) { $EnvAgentName } else { '(no configurado)' })"
    if ($EnvDatabaseUrl) {
        $masked = $EnvDatabaseUrl -replace '://([^:]+):([^@]+)@', '://$1:***@'
        Write-Host "DATABASE_URL: $masked"
    } else {
        Write-Host "DATABASE_URL: (no configurado)" -ForegroundColor Red
    }

    if ($EnvDatabaseUrl -match '@([^:/]+):(\d+)/') {
        $dbHost = $matches[1]
        $dbPort = $matches[2]
        Write-Host ""
        Write-Host "--- Conexión a la base central ($dbHost`:$dbPort) ---" -ForegroundColor Cyan
        $tcpTest = Test-NetConnection -ComputerName $dbHost -Port $dbPort -WarningAction SilentlyContinue
        if ($tcpTest.TcpTestSucceeded) {
            Write-Host "Llega al puerto $dbPort de $dbHost -- OK." -ForegroundColor Green
        } else {
            Write-Host "NO llega al puerto $dbPort de $dbHost (ping: $($tcpTest.PingSucceeded))." -ForegroundColor Red
            Write-Host "Si el ping sí llega pero el puerto no, revisá que la central ya tenga" -ForegroundColor DarkGray
            Write-Host "PostgreSQL corriendo y el Firewall de Windows abierto ahí (ver deploy\docker\README.md)." -ForegroundColor DarkGray
        }
    }

    Write-Host ""
    Write-Host "--- Últimas líneas del log de la tarea (Visor de eventos) ---" -ForegroundColor Cyan
    try {
        Get-WinEvent -FilterHashtable @{ LogName = "Microsoft-Windows-TaskScheduler/Operational" } -MaxEvents 10 -ErrorAction Stop |
            Where-Object { $_.Message -like "*$TaskName*" } |
            Select-Object TimeCreated, Id, Message |
            Format-Table -AutoSize -Wrap | Out-String | Write-Host
    } catch {
        Write-Host "No se pudo leer el Visor de eventos: $($_.Exception.Message)" -ForegroundColor DarkGray
    }
}
