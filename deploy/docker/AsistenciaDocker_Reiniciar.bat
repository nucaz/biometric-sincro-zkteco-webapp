@echo off
title Asistencia Docker - Reiniciar
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0manage.ps1" -Action Restart
echo.
pause
