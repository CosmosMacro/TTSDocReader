@echo off
setlocal ENABLEDELAYEDEXPANSION
:: Change to repo root (this script lives in scripts\)
cd /d "%~dp0.."

echo [Setup] Creating virtual environment if missing...
if not exist .\.venv\Scripts\python.exe (
  py -3 -m venv .venv || (
    echo [Setup] Failed to create venv. Ensure Python is installed and py launcher works.
    exit /b 1
  )
)

call .\.venv\Scripts\activate.bat
if errorlevel 1 (
  echo [Setup] Failed to activate venv.
  exit /b 1
)

echo [Setup] Upgrading pip...
python -m pip install --upgrade pip >nul 2>&1

echo [Setup] Installing Windows Piper requirements...
pip install -r requirements-windows-piper.txt
if errorlevel 1 (
  echo [Setup] pip install failed. Check your network and try again.
  exit /b 1
)

:: Ensure .env exists
if not exist .env (
  copy /Y .env.sample .env >nul
)

:: Append Piper config if not present
set ADDED=0
findstr /b /c:"TTS_BACKEND=" .env >nul || (
  echo TTS_BACKEND=piper>>.env
  set ADDED=1
)
set PIPER_EXE=%CD%\third_party\piper\piper\piper.exe
if exist "%PIPER_EXE%" (
  findstr /b /c:"PIPER_BIN=" .env >nul || (
    echo PIPER_BIN=%PIPER_EXE%>>.env
    set ADDED=1
  )
)
findstr /b /c:"PIPER_VOICES_DIR=" .env >nul || (
  echo PIPER_VOICES_DIR=%CD%\third_party\piper>>.env
  set ADDED=1
)

if %ADDED%==1 (
  echo [Setup] Updated .env with Piper defaults.
)

echo [Setup] Done.
exit /b 0

