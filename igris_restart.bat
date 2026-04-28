@echo off
echo Killing IGRIS on port 7777...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":7777" 2^>nul') do (
    taskkill /F /PID %%a 2>nul
)
timeout /t 2 /nobreak >nul
echo Starting IGRIS...
cd /d C:\Igris\repo\IGRIS_DEVIN
call .venv\Scripts\activate.bat
python -m igris web
