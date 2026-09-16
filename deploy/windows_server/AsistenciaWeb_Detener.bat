@echo off
title Asistencia - Detener servicio
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0service.ps1" -Action Stop
echo.
echo NOTA: la tarea "AsistenciaSync" sigue su horario normal (cada 15 min);
echo esto solo detiene el panel web (AsistenciaWeb).
echo.
pause
