@echo off
title Asistencia - Iniciar servicio
:: Se relanza pidiendo permisos de administrador si hace falta (necesarios
:: para controlar una tarea programada que corre como SYSTEM).
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0service.ps1" -Action Start
echo.
pause
