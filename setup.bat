@echo off
setlocal

echo.
echo  ====================================================
echo   J.A.R.V.I.S. setup
echo  ====================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python is not on PATH. Install Python 3.10+ first.
  pause
  exit /b 1
)

if not exist venv (
  echo [py]  creating virtual environment...
  python -m venv venv
)

call venv\Scripts\activate.bat

echo [py]  upgrading pip...
python -m pip install --upgrade pip --disable-pip-version-check >nul

echo [py]  installing requirements...
pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] pip install failed. Check requirements.txt.
  pause
  exit /b 1
)

echo [browser] installing Playwright Chromium runtime...
python -m playwright install chromium
if errorlevel 1 (
  echo [warn] Playwright browser install failed. Browser control will be unavailable until this succeeds.
)

if not exist .env (
  echo [env] creating .env from .env.example...
  copy /Y .env.example .env >nul
)

if not exist data            mkdir data
if not exist data\logs       mkdir data\logs
if not exist data\backups    mkdir data\backups
if not exist data\sandbox    mkdir data\sandbox

echo.
echo [web] checking for Node.js...
where node >nul 2>&1
if errorlevel 1 (
  echo [warn] Node.js not found on PATH.
  echo        Install Node 18+ from https://nodejs.org then re-run setup.bat
  echo        to build the cinematic web frontend.
  echo        ^(Backend will still run; it serves a placeholder until frontend is built.^)
  goto :done
)

pushd web
echo [web] installing npm dependencies ^(this can take a minute^)...
call npm install --silent
if errorlevel 1 (
  echo [ERROR] npm install failed.
  popd
  pause
  exit /b 1
)
echo [web] building frontend ^(production bundle^)...
call npm run build
if errorlevel 1 (
  echo [ERROR] npm run build failed.
  popd
  pause
  exit /b 1
)
popd

:done
echo.
echo  ====================================================
echo   Done.
echo     1. Edit .env  ^(LLM_API_KEY etc.^)
echo     2. Edit config.yaml  ^(model endpoint + provider^)
echo     3. Run:  run.bat
echo  ====================================================
echo.
pause
