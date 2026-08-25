@echo off
REM One-time setup: create a virtual environment and install dependencies.
setlocal
cd /d "%~dp0"

echo Creating virtual environment...
python -m venv .venv || goto :err

echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :err

echo.
echo Setup complete. Run KeyTrends.bat to start tracking.
pause
exit /b 0

:err
echo.
echo Setup failed. Make sure Python 3.10+ is installed and on your PATH.
pause
exit /b 1
