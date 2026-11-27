@echo off
REM Xem lai so lenh thu nghiem hang tuan bang Claude Code (chi doc, chi ghi vao logs\), roi gui tom tat Telegram.
REM Task Scheduler goi luc 16:00 thu 6 (register-task.ps1). Chay tay: scripts\weekly-review.bat
chcp 65001 >nul
cd /d "%~dp0.."
if not exist logs mkdir logs
del /q logs\review-telegram.txt 2>nul
set PY=backend\.venv\Scripts\python.exe -X utf8 -c
%PY% "import sys; sys.path.insert(0, 'backend'); from app.db import connect; from app.core.paper import review_data; open('logs/review-data.txt', 'w', encoding='utf-8').write(review_data(connect()))"
type scripts\weekly-review.md | claude -p --max-turns 40 --allowedTools "Read" "Grep" "Glob" "Edit(./logs/**)" "Write(./logs/**)" > logs\review-last-run.txt 2>&1
if exist logs\review-telegram.txt goto send
%PY% "import sys; sys.path.insert(0, 'backend'); from app import notify; notify.enabled() and notify.send_text('!! Xem lai so thu nghiem tuan nay bi loi: xem logs/review-last-run.txt')"
goto end
:send
%PY% "import sys; sys.path.insert(0, 'backend'); from app import notify; notify.enabled() and notify.send_text(open('logs/review-telegram.txt', encoding='utf-8').read())"
:end
