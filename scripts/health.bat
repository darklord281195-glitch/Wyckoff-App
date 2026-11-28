@echo off
REM Kiem tra suc khoe he thong (quet cuoi ngay, du lieu, task, sao luu...). Co muc loi thi gui Telegram, toi da 1 lan/ngay.
REM Task Scheduler goi luc 16:30 thu 2-6 voi --notify (register-task.ps1). Chay tay: scripts\health.bat
chcp 65001 >nul
cd /d "%~dp0..\backend"
".venv\Scripts\python.exe" -X utf8 -m app.health %*
