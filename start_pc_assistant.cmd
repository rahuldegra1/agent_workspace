@echo off
setlocal

set "APP_DIR=%LOCALAPPDATA%\Programs\PC Assistant"
set "APP_EXE=%APP_DIR%\PC Assistant.exe"

if exist "%APP_EXE%" (
    start "" "%APP_EXE%"
    exit /b 0
)

powershell -ExecutionPolicy Bypass -File "%~dp0build_windows_app.ps1"
if exist "%APP_EXE%" (
    start "" "%APP_EXE%"
) else (
    echo PC Assistant installation failed.
    exit /b 1
)
