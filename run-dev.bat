@echo off
:: Dev mode — launches both the Python backend AND the Vite dev server (HMR).
:: Open http://127.0.0.1:5173 for the Vite-proxied frontend.
setlocal

if not exist venv\Scripts\activate.bat (
  echo [ERROR] venv not found. Run setup.bat first.
  pause
  exit /b 1
)

start "JARVIS backend"  cmd /k call venv\Scripts\activate.bat ^&^& python -m jarvis.main --no-browser
start "JARVIS frontend" cmd /k cd web ^&^& npm run dev
