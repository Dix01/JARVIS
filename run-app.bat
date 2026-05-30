@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1

set "ROOT=%~dp0"
set "LOG=%ROOT%run-app.log"

echo. > "%LOG%"
call :log "=== JARVIS run-app.bat started %DATE% %TIME% ==="
call :log "ROOT = %ROOT%"

where node >nul 2>&1
if errorlevel 1 goto :no_node
for /f "tokens=*" %%v in ('node --version 2^>^&1') do call :log "node %%v"

if not exist "%ROOT%venv\Scripts\activate.bat" goto :no_venv
call :log "venv OK"

if not exist "%ROOT%electron\node_modules" goto :npm_install
goto :launch

:npm_install
call :log "node_modules missing - running npm install (first time, ~30s)..."
echo.
echo  Installing Electron dependencies (one-time setup)...
echo  This may take up to 60 seconds. Please wait.
echo.
pushd "%ROOT%electron"
call npm install >> "%LOG%" 2>&1
set _ERR=!errorlevel!
popd
if not !_ERR! == 0 goto :npm_failed
call :log "npm install OK"

:launch
call :log "Launching Electron (npm start)..."
echo.
echo  Launching JARVIS...
echo  This window can be minimized. Close the JARVIS window to exit.
echo.
pushd "%ROOT%electron"
call npm start >> "%LOG%" 2>&1
set _EXIT=!errorlevel!
popd

call :log "Electron exited with code !_EXIT!"
if not !_EXIT! == 0 (
  echo.
  echo  JARVIS exited with error code !_EXIT!
  echo  Full log: %LOG%
  echo.
)
pause
exit /b !_EXIT!

:no_node
call :log "[ERROR] node.exe not found in PATH."
echo.
echo  Node.js is required but was not found in PATH.
echo  Download from: https://nodejs.org/
echo.
echo  Full log saved to: %LOG%
pause
exit /b 1

:no_venv
call :log "[ERROR] venv not found at %ROOT%venv"
echo.
echo  Python virtual environment not found.
echo  Run setup.bat first, then retry.
echo.
echo  Full log saved to: %LOG%
pause
exit /b 1

:npm_failed
call :log "[ERROR] npm install failed exit code !_ERR!"
echo.
echo  npm install failed. See full log: %LOG%
echo.
pause
exit /b 1

:log
echo [%TIME%] %~1
echo [%TIME%] %~1 >> "%LOG%"
goto :eof
