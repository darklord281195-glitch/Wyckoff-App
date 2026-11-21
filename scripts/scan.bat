@echo off
REM Quet Wyckoff cuoi ngay + gui Telegram. Task Scheduler goi file nay luc 15:30 thu 2-6.
chcp 65001 >nul
cd /d "%~dp0..\backend"
".venv\Scripts\python.exe" -X utf8 -m app.scan %*
