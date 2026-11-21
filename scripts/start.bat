@echo off
REM Mo web Wyckoff Scanner: backend (cong 8000) + frontend (cong 3000)
chcp 65001 >nul
set ROOT=%~dp0..
start "Wyckoff API" cmd /k "cd /d %ROOT%\backend && .venv\Scripts\python.exe -X utf8 -m uvicorn app.api:app --host 127.0.0.1 --port 8000"
if not exist "%ROOT%\frontend\.next\BUILD_ID" (
  echo Dang build frontend lan dau...
  cd /d %ROOT%\frontend && call npm run build
)
start "Wyckoff Web" cmd /k "cd /d %ROOT%\frontend && npx next start -p 3000"
timeout /t 5 >nul
start http://localhost:3000
