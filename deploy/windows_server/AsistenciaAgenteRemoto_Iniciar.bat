@echo off
title Asistencia - Iniciar agente remoto
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0agente_remoto_servicio.ps1" -Action Start
echo.
pause
