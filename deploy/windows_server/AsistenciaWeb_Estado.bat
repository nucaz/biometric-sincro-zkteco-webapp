@echo off
title Asistencia - Estado del servicio
:: Consultar el estado no necesita permisos de administrador.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0service.ps1" -Action Status
echo.
pause
