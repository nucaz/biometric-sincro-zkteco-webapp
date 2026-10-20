<#
.SYNOPSIS
  Interruptor de emergencia para el despliegue con Docker (Windows):
  inicia, detiene, reinicia, muestra estado o diagnostica. Detecta solo
  si esta máquina es "servidor central" o "agente remoto" leyendo
  deploy\docker\.deploy_mode (lo escribe install.ps1).

  No lo llames directo si prefieres los .bat de doble clic, en esta
  misma carpeta: AsistenciaDocker_Iniciar / _Detener / _Reiniciar /
  _Estado / _Diagnostico.

  A diferencia de los .bat de deploy\windows_server\, estos NO se auto-
  elevan a Administrador: Docker Desktop corre con la sesión del usuario
  que inició sesión, y abrir una consola elevada aparte puede terminar
  hablando con un Docker Desktop distinto (u ninguno). Corre este script
  con el usuario normal que ya tiene Docker Desktop abierto.

.PARAMETER Action
  Start | Stop | Restart | Status | Diagnose (por defecto: Status)

.EXAMPLE
  .\deploy\docker\manage.ps1 -Action Restart
#>
param(
    [ValidateSet("Start", "Stop", "Restart", "Status", "Diagnose")]
    [string]$Action = "Status"
)

$DockerDir = $PSScriptRoot
$RepoRoot = Resolve-Path (Join-Path $DockerDir "..\..")
$MarkerFile = Join-Path $DockerDir ".deploy_mode"

if (-not (Test-Path $MarkerFile)) {
    Write-Warning "No se encontró deploy\docker\.deploy_mode -- ¿ya corriste install.ps1 en esta máquina?"
    exit 1
}
$Mode = (Get-Content $MarkerFile -Raw).Trim()

if ($Mode -eq "central") {
    $ComposeFile = Join-Path $RepoRoot "docker-compose.yml"
    $EnvFile = Join-Path $RepoRoot ".env"
    $WorkDir = $RepoRoot
    $Services = @("db", "web", "sync")
} elseif ($Mode -eq "agent") {
    $ComposeFile = Join-Path $DockerDir "docker-compose.agent.yml"
    $EnvFile = Join-Path $DockerDir ".env"
    $WorkDir = $DockerDir
    $Services = @("agent")
} else {
    Write-Warning "deploy\docker\.deploy_mode tiene un valor desconocido: '$Mode' (se esperaba 'central' o 'agent'). Vuelve a correr install.ps1."
    exit 1
}

function Invoke-Compose {
    # $ComposeArgs llega como UN array por un parámetro con nombre, nunca
    # como tokens sueltos en la llamada -- si "up","-d" se pasaran sueltos
    # (p.ej. "Invoke-Compose up -d"), PowerShell intenta primero hacerlos
    # calzar como parámetros con nombre de ESTA función antes que como
    # posicionales: "-d" calza por prefijo único con el parámetro común
    # "-Debug" y nunca llega a Docker -- visto en esta sesión: "docker
    # compose up" corrió SIN el "-d" real, se quedó pegado en primer plano
    # mostrando logs en vez de desprenderse.
    param([string[]]$ComposeArgs)
    Push-Location $WorkDir
    try {
        & docker compose -f $ComposeFile --env-file $EnvFile @ComposeArgs
    } finally {
        Pop-Location
    }
}

switch ($Action) {
    "Start" {
        Write-Host "Iniciando ($Mode)..." -ForegroundColor Cyan
        Invoke-Compose -ComposeArgs @("up", "-d")
    }
    "Stop" {
        Write-Host "Deteniendo ($Mode)..." -ForegroundColor Cyan
        Invoke-Compose -ComposeArgs @("stop")
    }
    "Restart" {
        Write-Host "Reiniciando ($Mode)..." -ForegroundColor Cyan
        Invoke-Compose -ComposeArgs @("restart")
    }
}

if ($Action -in @("Start", "Stop", "Restart", "Status")) {
    Write-Host ""
    Write-Host "=== Estado actual ($Mode) ===" -ForegroundColor White
    Invoke-Compose -ComposeArgs @("ps")
}

if ($Action -eq "Diagnose") {
    Write-Host "=== Diagnóstico del despliegue Docker ($Mode) ===" -ForegroundColor White
    Write-Host ""

    Write-Host "--- Docker ---" -ForegroundColor Cyan
    docker --version
    docker compose version
    $dockerUp = $true
    docker info | Out-Null
    if ($LASTEXITCODE -ne 0) {
        $dockerUp = $false
        Write-Host "Docker Desktop no responde -- ábrelo y espera a que termine de iniciar." -ForegroundColor Red
    } else {
        Write-Host "Docker Desktop responde correctamente." -ForegroundColor Green
    }

    if ($dockerUp) {
        Write-Host ""
        Write-Host "--- Contenedores ---" -ForegroundColor Cyan
        Invoke-Compose -ComposeArgs @("ps")

        foreach ($svc in $Services) {
            Write-Host ""
            Write-Host "--- Últimas líneas de log: $svc ---" -ForegroundColor Cyan
            Invoke-Compose -ComposeArgs @("logs", "--tail", "15", $svc)
        }

        if ($Mode -eq "central") {
            Write-Host ""
            Write-Host "--- Base de datos ---" -ForegroundColor Cyan
            Invoke-Compose -ComposeArgs @("exec", "-T", "db", "pg_isready")
            if ($LASTEXITCODE -eq 0) {
                Write-Host "PostgreSQL responde." -ForegroundColor Green
            } else {
                Write-Host "PostgreSQL NO responde -- revisa el log de 'db' arriba." -ForegroundColor Red
            }

            $envMap = @{}
            if (Test-Path $EnvFile) {
                foreach ($line in Get-Content $EnvFile) {
                    if ($line -match '^\s*WEB_PORT\s*=\s*(.*)$') { $envMap["WEB_PORT"] = $matches[1].Trim() }
                }
            }
            $port = if ($envMap["WEB_PORT"]) { $envMap["WEB_PORT"] } else { "5000" }
            Write-Host ""
            Write-Host "--- Panel web (http://localhost:$port) ---" -ForegroundColor Cyan
            try {
                $resp = Invoke-WebRequest -Uri "http://localhost:$port/login" -UseBasicParsing -TimeoutSec 5
                Write-Host "Responde con código HTTP $($resp.StatusCode)." -ForegroundColor Green
            } catch {
                Write-Host "No se pudo conectar al panel en el puerto $port -: $($_.Exception.Message)" -ForegroundColor Red
            }
        } else {
            Write-Host ""
            Write-Host "--- Comandos pendientes para este agente ---" -ForegroundColor Cyan
            Write-Host "Revisa la pestaña Dispositivos del panel central -- un comando que se queda" -ForegroundColor DarkGray
            Write-Host "'pendiente' por mucho tiempo suele ser este agente caído o sin red hacia la central." -ForegroundColor DarkGray
        }
    }

    Write-Host ""
    Write-Host "--- Espacio en disco usado por Docker ---" -ForegroundColor Cyan
    docker system df
}
