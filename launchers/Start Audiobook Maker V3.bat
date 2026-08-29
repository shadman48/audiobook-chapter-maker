@echo off
setlocal
title Audiobook Maker V3.49
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_v3.ps1" %*
if errorlevel 1 pause
