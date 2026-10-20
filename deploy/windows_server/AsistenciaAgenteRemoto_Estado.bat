@echo off
title Asistencia - Estado del agente remoto
:: Consultar el estado no necesita permisos de administrador.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0agente_remoto_servicio.ps1" -Action Status
echo.
pause
