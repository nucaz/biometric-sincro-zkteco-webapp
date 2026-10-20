@echo off
title Asistencia Docker - Diagnostico
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0manage.ps1" -Action Diagnose
echo.
pause
