@echo off
title Asistencia Docker - Detener
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0manage.ps1" -Action Stop
echo.
pause
