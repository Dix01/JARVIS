@echo off
setlocal

if not exist venv\Scripts\activate.bat (
  echo [ERROR] venv not found. Run setup.bat first.
  pause
  exit /b 1
)

:: Force UTF-8 so the banner + log lines render correctly on Windows.
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

call venv\Scripts\activate.bat
python -m jarvis.main %*


pause