<#
.SYNOPSIS
  Interruptor de emergencia para el panel central en Windows: inicia,
  detiene, reinicia o muestra el estado de las Tareas Programadas que
  install.ps1 registro (AsistenciaWeb + AsistenciaSync). Siempre imprime
  el nombre exacto de la tarea sobre la que actua y su estado resultante.

  No lo llames directo si prefieres los botones de doble clic:
    AsistenciaWeb_Iniciar.bat
    AsistenciaWeb_Detener.bat
    AsistenciaWeb_Reiniciar.bat
    AsistenciaWeb_Estado.bat
  (los cuatro estan en esta misma carpeta y ya piden permisos de
  administrador solos si hace falta.)

.PARAMETER Action
  Start | Stop | Restart | Status (por defecto: Status)

.EXAMPLE
  .\deploy\windows_server\service.ps1 -Action Restart
#>
param(
    [ValidateSet("Start", "Stop", "Restart", "Status")]
    [string]$Action = "Status"
)

$WebTaskName = "AsistenciaWeb"
$SyncTaskName = "AsistenciaSync"

$IsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
if (-not $IsAdmin -and $Action -ne "Status") {
    Write-Warning "Esta accion ($Action) necesita PowerShell como Administrador. Cierra esta ventana y vuelve a abrirla con 'Ejecutar como administrador', o usa el .bat correspondiente (ya pide permisos solo)."
    exit 1
}

function Show-TaskStatus([string]$TaskName) {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) {
        Write-Host "Tarea: $TaskName -- NO ENCONTRADA" -ForegroundColor Red
        Write-Host "  (Se corrio deploy\windows_server\install.ps1 como Administrador?)" -ForegroundColor DarkGray
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
        Write-Host "    Ultima ejecucion:  $($info.LastRunTime)   Resultado: $($info.LastTaskResult)"
        Write-Host "    Proxima ejecucion: $($info.NextRunTime)"
    }
}

switch ($Action) {
    "Start" {
        Write-Host "Iniciando la tarea '$WebTaskName'..." -ForegroundColor Cyan
        Start-ScheduledTask -TaskName $WebTaskName
        Start-Sleep -Seconds 2
    }
    "Stop" {
        Write-Host "Deteniendo la tarea '$WebTaskName'..." -ForegroundColor Cyan
        Stop-ScheduledTask -TaskName $WebTaskName -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
    }
    "Restart" {
        Write-Host "Reiniciando la tarea '$WebTaskName'..." -ForegroundColor Cyan
        Stop-ScheduledTask -TaskName $WebTaskName -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        Start-ScheduledTask -TaskName $WebTaskName
        Start-Sleep -Seconds 2
    }
}

Write-Host ""
Write-Host "=== Estado actual de las tareas de Asistencia ===" -ForegroundColor White
Show-TaskStatus $WebTaskName
Show-TaskStatus $SyncTaskName
Write-Host ""

if ($Action -in @("Start", "Restart")) {
    $task = Get-ScheduledTask -TaskName $WebTaskName -ErrorAction SilentlyContinue
    if ($task -and $task.State -eq "Running") {
        Write-Host "Panel disponible en: http://localhost:5000" -ForegroundColor Green
    } elseif ($task) {
        Write-Warning "La tarea '$WebTaskName' quedo en estado '$($task.State)', no 'Running'. Revisa el Visor de eventos (Registros de Windows > Sistema) o vuelve a correr install.ps1."
    }
}
