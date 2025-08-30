@echo off
setlocal
cd /d "%~dp0.."

:: Ensure venv and deps
if not exist .\.venv\Scripts\python.exe (
  call scripts\setup_piper_windows.bat || exit /b 1
)

call .\.venv\Scripts\activate.bat
if errorlevel 1 (
  echo [Run] Failed to activate venv.
  exit /b 1
)

set PORT=%1
if "%PORT%"=="" set PORT=8000

echo [Run] Starting web UI on http://127.0.0.1:%PORT% ...
python -m uvicorn app.main:app --host 127.0.0.1 --port %PORT%

endlocal
exit /b %ERRORLEVEL%

