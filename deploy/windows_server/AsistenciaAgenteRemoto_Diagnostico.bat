@echo off
title Asistencia - Diagnostico del agente remoto
:: Diagnosticar no necesita permisos de administrador.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0agente_remoto_servicio.ps1" -Action Diagnose
echo.
pause
