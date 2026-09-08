@echo off
REM Pull my Garmin data into the local .\data folder (read-only).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\python.exe -m pip install -r requirements.txt
)
.venv\Scripts\python.exe sync.py %*
echo.
pause
