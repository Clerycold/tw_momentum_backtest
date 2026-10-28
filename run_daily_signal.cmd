@echo off
rem Windows Task Scheduler entry point: weekdays 20:00 -> daily asset-allocation signal via Telegram
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" scripts\daily_signal.py >> logs\daily_signal_stdout.log 2>&1
