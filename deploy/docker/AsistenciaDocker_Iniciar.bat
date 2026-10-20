@echo off
title Asistencia Docker - Iniciar
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0manage.ps1" -Action Start
echo.
pause
