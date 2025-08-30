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

:: Pass-through args to CLI
python cli.py %*

endlocal
exit /b %ERRORLEVEL%

