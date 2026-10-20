@echo off
title Asistencia Docker - Estado
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0manage.ps1" -Action Status
echo.
pause
