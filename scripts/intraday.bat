@echo off
REM Canh bao gia trong phien (cham cat lo / muc tieu / vung mua). Task Scheduler goi luc 9:10 thu 2-6 voi --loop.
chcp 65001 >nul
cd /d "%~dp0..\backend"
".venv\Scripts\python.exe" -X utf8 -m app.intraday %*
