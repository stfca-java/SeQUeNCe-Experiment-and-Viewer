@echo off
setlocal
set "viewer_python=%~dp0..\SeQUeNCe\.venv\Scripts\python.exe"
if not exist "%viewer_python%" set "viewer_python=python"
"%viewer_python%" "%~dp0app.py" %*
if errorlevel 1 (
    echo See README.md in the sequence-visualizer folder for setup.
    pause
    exit /b 1
)
